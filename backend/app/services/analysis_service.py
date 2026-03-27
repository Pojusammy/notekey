"""Melody and harmonic analysis service — wraps Basic Pitch.

Three analysis modes:

**Standard mode** (default):
  Monophonic lead melody extraction with conservative filtering.

**Fast mode** (`analysis_mode="fast"`):
  Monophonic lead melody tuned for interludes, runs, syncopation.

**Roots mode** (`analysis_mode="roots"`):
  Polyphonic harmonic root-note detection.  Analyses all active
  pitch classes in time windows, matches against chord templates,
  and returns a cleaned root progression (e.g. C → Am → Dm → G).
"""

import os
import subprocess
import tempfile
from dataclasses import dataclass

import numpy as np

from app.services.solfa_service import frequency_to_note, note_to_solfa

# ── MIDI reference ────────────────────────────────────────────────
MIDI_C3 = 48
MIDI_C6 = 84

# ── Basic Pitch constants ─────────────────────────────────────────
_BP_FPS = 86                # frames per second (ANNOTATIONS_FPS)
_BP_BINS_PER_SEMI = 3       # contour resolution
_BP_BASE_MIDI = 21          # A0 = MIDI 21 (27.5 Hz)
_BP_N_CONTOUR_BINS = 264    # 88 semitones × 3 bins


# ── Mode-specific parameter sets ─────────────────────────────────

@dataclass(frozen=True)
class AnalysisParams:
    """All tuneable knobs for the analysis pipeline."""
    # Basic Pitch inference
    onset_threshold: float
    frame_threshold: float
    minimum_note_length: float   # milliseconds (Basic Pitch param)

    # Post-filter
    min_amplitude: float
    min_duration: float          # seconds — hard floor
    melody_window: float         # seconds — onset grouping
    merge_semitone_tol: int      # semitones for consecutive merge
    merge_max_gap: float         # seconds — max gap to merge across
    smoothing_window: int        # median-filter kernel size (odd)

    # Onset splitting (fast mode only)
    onset_split: bool
    onset_energy_threshold: float

    # Short-note cleanup
    cleanup_min_dur: float
    cleanup_min_neighbours: int

    # Pitch refinement
    trim_ratio: float            # fraction of note to trim from each edge
    min_stable_frames: int       # minimum frames in stable region
    cents_ambiguity: float       # cents threshold — beyond this, lower confidence
    octave_jump_limit: int       # max semitone jump before octave correction


STANDARD_PARAMS = AnalysisParams(
    onset_threshold=0.5,
    frame_threshold=0.3,
    minimum_note_length=127.7,
    min_amplitude=0.25,
    min_duration=0.15,
    melody_window=0.06,
    merge_semitone_tol=1,
    merge_max_gap=0.15,
    smoothing_window=3,
    onset_split=False,
    onset_energy_threshold=0.0,
    cleanup_min_dur=0.08,
    cleanup_min_neighbours=0,
    # Pitch refinement
    trim_ratio=0.15,             # trim 15% from each edge
    min_stable_frames=3,
    cents_ambiguity=35.0,        # >35 cents from note center = ambiguous
    octave_jump_limit=9,         # 9 semitones — beyond this, suspect octave error
)

FAST_PARAMS = AnalysisParams(
    onset_threshold=0.35,
    frame_threshold=0.2,
    minimum_note_length=58.0,
    min_amplitude=0.18,
    min_duration=0.05,
    melody_window=0.035,
    merge_semitone_tol=0,
    merge_max_gap=0.06,
    smoothing_window=1,
    onset_split=True,
    onset_energy_threshold=1.4,
    cleanup_min_dur=0.04,
    cleanup_min_neighbours=1,
    # Pitch refinement — less trimming for short notes
    trim_ratio=0.10,             # trim only 10% from each edge
    min_stable_frames=2,
    cents_ambiguity=40.0,        # slightly more tolerant for fast passages
    octave_jump_limit=9,
)

_PARAMS = {
    "standard": STANDARD_PARAMS,
    "fast": FAST_PARAMS,
}


def _get_params(mode: str) -> AnalysisParams:
    return _PARAMS.get(mode, STANDARD_PARAMS)


# ── Audio normalisation ──────────────────────────────────────────

def parse_time_string(time_str: str | None) -> float | None:
    """Parse a time string like '1:30' or '90' into seconds."""
    if not time_str or not time_str.strip():
        return None
    parts = time_str.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return float(parts[0])


def normalize_audio(
    input_path: str,
    start_time: float | None = None,
    end_time: float | None = None,
) -> str:
    """Normalize any audio/video to mono WAV at 22050 Hz, with optional trimming."""
    output = tempfile.mktemp(suffix=".wav")
    cmd = ["ffmpeg", "-y"]

    if start_time is not None and start_time > 0:
        cmd += ["-ss", str(start_time)]

    cmd += ["-i", input_path]

    if end_time is not None and start_time is not None:
        duration = end_time - start_time
        if duration > 0:
            cmd += ["-t", str(duration)]
    elif end_time is not None:
        cmd += ["-t", str(end_time)]

    cmd += [
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "22050",
        "-ac", "1",
        output,
    ]

    subprocess.run(cmd, check=True, capture_output=True)
    return output


# ── Pipeline stages ──────────────────────────────────────────────

def _filter_events(
    note_events: list,
    midi_lo: int,
    midi_hi: int,
    p: AnalysisParams,
) -> list:
    """Pitch-range + amplitude + duration gating."""
    out = []
    for ev in note_events:
        midi = int(ev[2])
        amp = float(ev[3])
        dur = float(ev[1]) - float(ev[0])
        if midi_lo <= midi <= midi_hi and amp >= p.min_amplitude and dur >= p.min_duration:
            out.append(ev)
    return out


def _select_melody(events: list, p: AnalysisParams) -> list:
    """Monophonic melody extraction.

    For each onset window keep a single note.  Among candidates prefer
    mid-high pitches and, when amplitudes are close, the note nearest
    in pitch to the previous selection (continuity).
    """
    events.sort(key=lambda e: (float(e[0]), -float(e[3])))

    melody: list = []
    prev_midi: float | None = None
    i = 0

    while i < len(events):
        t0 = float(events[i][0])
        group = [events[i]]
        j = i + 1
        while j < len(events) and float(events[j][0]) - t0 < p.melody_window:
            group.append(events[j])
            j += 1

        def _score(ev, _prev=prev_midi):
            midi = int(ev[2])
            amp = float(ev[3])
            octave_above_c4 = (midi - 60) / 12.0
            range_bias = max(0.0, octave_above_c4 * 0.15)
            cont_bonus = 0.0
            if _prev is not None:
                semitone_dist = abs(midi - _prev)
                cont_bonus = max(0.0, 0.2 - semitone_dist * 0.015)
            return amp + range_bias + cont_bonus

        best = max(group, key=_score)
        melody.append(best)
        prev_midi = int(best[2])
        i = j

    return melody


def _onset_split(events: list, wav_path: str, p: AnalysisParams) -> list:
    """Split long notes at detected energy onsets."""
    if not p.onset_split or not events:
        return events

    try:
        import librosa
    except ImportError:
        return events

    y, sr = librosa.load(wav_path, sr=22050, mono=True)
    onset_frames = librosa.onset.onset_detect(
        y=y, sr=sr, hop_length=256, backtrack=True, units="frames",
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=256)

    split: list = []
    for ev in events:
        start = float(ev[0])
        end = float(ev[1])
        midi = int(ev[2])
        amp = float(ev[3])
        rest = ev[4] if len(ev) > 4 else 0.0

        margin = 0.02
        inner = [t for t in onset_times if start + margin < t < end - margin]

        if not inner:
            split.append(ev)
            continue

        boundaries = [start] + sorted(inner) + [end]
        for k in range(len(boundaries) - 1):
            seg_start = boundaries[k]
            seg_end = boundaries[k + 1]
            if seg_end - seg_start >= p.min_duration:
                split.append((seg_start, seg_end, midi, amp, rest))

    return split


# ── NEW: Contour-based pitch refinement ──────────────────────────

def _refine_pitches(
    events: list,
    contour: np.ndarray,
    p: AnalysisParams,
) -> list:
    """Re-estimate pitch for each note using Basic Pitch's raw contour.

    For each note segment:
      1. Map time range → contour frame range
      2. Trim attack/release edges (trim_ratio from each side)
      3. Extract pitch estimate from the stable middle frames using
         amplitude-weighted median across contour bins
      4. Quantize to nearest MIDI note with cents-aware confidence
      5. Store per-note stability score for later confidence weighting

    Returns events with refined MIDI pitch and an added stability field.
    Event format: (start, end, refined_midi, amplitude, stability)
    """
    n_frames = contour.shape[0]
    refined = []

    for ev in events:
        start_t = float(ev[0])
        end_t = float(ev[1])
        orig_midi = int(ev[2])
        amp = float(ev[3])

        # Map to contour frames
        frame_start = int(start_t * _BP_FPS)
        frame_end = int(end_t * _BP_FPS)
        frame_start = max(0, min(frame_start, n_frames - 1))
        frame_end = max(frame_start + 1, min(frame_end, n_frames))

        n_seg_frames = frame_end - frame_start

        # Trim edges to get stable middle region
        trim = max(1, int(n_seg_frames * p.trim_ratio))
        stable_start = frame_start + trim
        stable_end = frame_end - trim

        # Ensure we have enough stable frames
        if stable_end - stable_start < p.min_stable_frames:
            # Fall back to full segment (minus 1 frame each side if possible)
            stable_start = frame_start + min(1, n_seg_frames // 4)
            stable_end = frame_end - min(1, n_seg_frames // 4)
            if stable_end <= stable_start:
                stable_start = frame_start
                stable_end = frame_end

        seg_contour = contour[stable_start:stable_end]  # shape: (frames, 264)

        if seg_contour.size == 0:
            refined.append((start_t, end_t, orig_midi, amp, 0.5))
            continue

        # Find the dominant pitch region: look around the original MIDI ±3 semitones
        # in contour bins
        orig_bin_center = (orig_midi - _BP_BASE_MIDI) * _BP_BINS_PER_SEMI + 1
        search_radius = 3 * _BP_BINS_PER_SEMI  # ±3 semitones = ±9 bins
        bin_lo = max(0, orig_bin_center - search_radius)
        bin_hi = min(_BP_N_CONTOUR_BINS, orig_bin_center + search_radius + 1)

        region = seg_contour[:, bin_lo:bin_hi]  # shape: (frames, ~18 bins)

        if region.size == 0 or region.max() < 0.01:
            refined.append((start_t, end_t, orig_midi, amp, 0.5))
            continue

        # For each frame, find the peak bin (sub-semitone pitch)
        frame_pitches = []
        frame_weights = []
        for f in range(region.shape[0]):
            frame_row = region[f]
            peak_idx = int(np.argmax(frame_row))
            peak_val = float(frame_row[peak_idx])

            if peak_val < 0.05:
                continue

            # Convert bin index back to fractional MIDI
            abs_bin = bin_lo + peak_idx
            frac_midi = _BP_BASE_MIDI + abs_bin / _BP_BINS_PER_SEMI

            frame_pitches.append(frac_midi)
            frame_weights.append(peak_val)

        if not frame_pitches:
            refined.append((start_t, end_t, orig_midi, amp, 0.5))
            continue

        pitches = np.array(frame_pitches)
        weights = np.array(frame_weights)

        # Weighted median: sort by pitch, find the weight-midpoint
        sort_idx = np.argsort(pitches)
        sorted_p = pitches[sort_idx]
        sorted_w = weights[sort_idx]
        cum_w = np.cumsum(sorted_w)
        half_w = cum_w[-1] / 2.0
        median_idx = int(np.searchsorted(cum_w, half_w))
        median_idx = min(median_idx, len(sorted_p) - 1)
        stable_pitch = float(sorted_p[median_idx])

        # Quantize: round to nearest semitone
        nearest_midi = round(stable_pitch)
        cents_off = (stable_pitch - nearest_midi) * 100.0

        # Pitch stability: std dev of frame pitches (in semitones)
        pitch_std = float(np.std(pitches)) if len(pitches) > 1 else 0.0

        # Stability score: 1.0 = perfectly stable, lower = less stable
        # Penalise high std (vibrato/drift) and high cents offset
        std_penalty = min(1.0, pitch_std / 1.5)  # 1.5 semitone std → 0 stability
        cents_penalty = min(1.0, abs(cents_off) / 50.0)  # 50 cents → 0 stability
        stability = max(0.1, 1.0 - 0.5 * std_penalty - 0.5 * cents_penalty)

        # If cents offset is very high (>ambiguity threshold), consider both candidates
        if abs(cents_off) > p.cents_ambiguity:
            # Check which of the two nearest semitones has more contour energy
            cand_lo = int(np.floor(stable_pitch))
            cand_hi = cand_lo + 1
            lo_bin = max(0, (cand_lo - _BP_BASE_MIDI) * _BP_BINS_PER_SEMI)
            hi_bin = max(0, (cand_hi - _BP_BASE_MIDI) * _BP_BINS_PER_SEMI)

            lo_energy = 0.0
            hi_energy = 0.0
            for b in range(max(0, lo_bin - 1), min(_BP_N_CONTOUR_BINS, lo_bin + 2)):
                lo_energy += float(seg_contour[:, b].sum())
            for b in range(max(0, hi_bin - 1), min(_BP_N_CONTOUR_BINS, hi_bin + 2)):
                hi_energy += float(seg_contour[:, b].sum())

            nearest_midi = cand_lo if lo_energy >= hi_energy else cand_hi
            stability *= 0.8  # reduce confidence for ambiguous pitches

        refined.append((start_t, end_t, nearest_midi, amp, stability))

    return refined


def _fix_octave_jumps(events: list, p: AnalysisParams) -> list:
    """Correct implausible octave jumps using melodic context.

    If a note is >octave_jump_limit semitones away from both its
    neighbours, and shifting it by ±12 would bring it closer,
    apply the octave correction.
    """
    if len(events) < 3:
        return events

    result = [list(ev) for ev in events]

    for i in range(len(result)):
        midi = int(result[i][2])

        # Get context: previous and next note pitches
        prev_midi = int(result[i - 1][2]) if i > 0 else None
        next_midi = int(result[i + 1][2]) if i < len(result) - 1 else None

        # Calculate distances to neighbours
        ctx_midis = [m for m in (prev_midi, next_midi) if m is not None]
        if not ctx_midis:
            continue

        avg_ctx = sum(ctx_midis) / len(ctx_midis)
        dist_to_ctx = abs(midi - avg_ctx)

        if dist_to_ctx <= p.octave_jump_limit:
            continue

        # Try shifting ±12 semitones
        for shift in (12, -12):
            candidate = midi + shift
            new_dist = abs(candidate - avg_ctx)
            if new_dist < dist_to_ctx and new_dist <= p.octave_jump_limit:
                result[i][2] = candidate
                # Reduce stability for corrected notes
                if len(result[i]) > 4:
                    result[i][4] = float(result[i][4]) * 0.85
                break

    return [tuple(ev) for ev in result]


def _smooth_pitches(events: list, p: AnalysisParams) -> list:
    """Median-filter pitch sequence to remove jitter.

    In fast mode (smoothing_window=1) this is an identity pass.
    """
    if len(events) <= p.smoothing_window or p.smoothing_window <= 1:
        return events

    midis = np.array([int(e[2]) for e in events], dtype=float)
    half = p.smoothing_window // 2
    smoothed_midis = midis.copy()

    for idx in range(len(midis)):
        lo = max(0, idx - half)
        hi = min(len(midis), idx + half + 1)
        smoothed_midis[idx] = round(float(np.median(midis[lo:hi])))

    out = []
    for ev, new_midi in zip(events, smoothed_midis):
        new_midi_int = int(new_midi)
        stability = float(ev[4]) if len(ev) > 4 else 0.5
        out.append((ev[0], ev[1], new_midi_int, ev[3], stability))
    return out


def _merge_consecutive(events: list, p: AnalysisParams) -> list:
    """Merge consecutive notes of the same (or very close) pitch."""
    if not events:
        return events

    merged: list = [list(events[0])]

    for ev in events[1:]:
        prev = merged[-1]
        prev_midi = int(prev[2])
        cur_midi = int(ev[2])
        gap = float(ev[0]) - float(prev[1])

        if abs(cur_midi - prev_midi) <= p.merge_semitone_tol and gap < p.merge_max_gap:
            prev[1] = ev[1]
            if float(ev[3]) > float(prev[3]):
                prev[2] = ev[2]
                prev[3] = ev[3]
            # Keep the better stability
            if len(prev) > 4 and len(ev) > 4:
                prev[4] = max(float(prev[4]), float(ev[4]))
        else:
            merged.append(list(ev))

    return merged


def _cleanup_short_notes(events: list, p: AnalysisParams) -> list:
    """Remove isolated micro-notes that are likely noise."""
    if p.cleanup_min_neighbours <= 0 or not events:
        return events

    WINDOW = 0.3
    out = []
    starts = [float(ev[0]) for ev in events]

    for idx, ev in enumerate(events):
        dur = float(ev[1]) - float(ev[0])
        if dur >= p.cleanup_min_dur:
            out.append(ev)
            continue

        t = starts[idx]
        neighbours = sum(
            1 for k, s in enumerate(starts)
            if k != idx and abs(s - t) <= WINDOW
        )
        if neighbours >= p.cleanup_min_neighbours:
            out.append(ev)

    return out


def _build_output(events: list, effective_key: str) -> dict:
    """Convert cleaned events to the API output format.

    Confidence is now a blend of amplitude and per-note pitch stability.
    """
    note_sequence = []
    solfa_sequence = []
    amplitudes = []
    stabilities = []

    for ev in events:
        ev_start = float(ev[0])
        ev_end = float(ev[1])
        midi_pitch = int(ev[2])
        amplitude = float(ev[3])
        stability = float(ev[4]) if len(ev) > 4 else 0.7

        frequency = 440.0 * (2 ** ((midi_pitch - 69) / 12))
        note_name, octave, _ = frequency_to_note(frequency)
        solfa = note_to_solfa(note_name, effective_key)

        note_sequence.append({
            "noteName": note_name,
            "octave": octave,
            "startTime": round(ev_start, 3),
            "duration": round(ev_end - ev_start, 3),
            "frequency": round(frequency, 2),
            "solfa": solfa,
        })
        solfa_sequence.append(solfa)
        amplitudes.append(amplitude)
        stabilities.append(stability)

    if amplitudes:
        avg_amp = float(np.mean(amplitudes))
        avg_stability = float(np.mean(stabilities))
        # Blend: 40% amplitude, 60% pitch stability
        raw_conf = 0.4 * (0.55 + avg_amp * 0.55) + 0.6 * avg_stability
        confidence = min(0.99, max(0.1, raw_conf))
    else:
        confidence = 0.0

    return {
        "noteSequence": note_sequence,
        "solfaSequence": solfa_sequence,
        "confidenceScore": round(confidence, 3),
    }


# ══════════════════════════════════════════════════════════════════
# ── Root-note analysis pipeline (polyphonic) ─────────────────────
# ══════════════════════════════════════════════════════════════════

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Chord templates: each maps a root pitch-class offset to a set of
# intervals from the root.  We test all 12 roots × all templates and
# score by how many active pitch classes match.
_CHORD_TEMPLATES = {
    "maj":    {0, 4, 7},
    "min":    {0, 3, 7},
    "dom7":   {0, 4, 7, 10},
    "maj7":   {0, 4, 7, 11},
    "min7":   {0, 3, 7, 10},
    "dim":    {0, 3, 6},
    "aug":    {0, 4, 8},
    "sus4":   {0, 5, 7},
    "sus2":   {0, 2, 7},
    "add9":   {0, 2, 4, 7},
    "6":      {0, 4, 7, 9},
    "min6":   {0, 3, 7, 9},
    "power":  {0, 7},
}

# Weights: how much a template match is worth (triads > extended)
_TEMPLATE_WEIGHTS = {
    "maj": 1.0, "min": 1.0, "dom7": 0.95, "maj7": 0.9, "min7": 0.9,
    "dim": 0.8, "aug": 0.8, "sus4": 0.75, "sus2": 0.75,
    "add9": 0.85, "6": 0.85, "min6": 0.85, "power": 0.6,
}

# Root analysis constants
_ROOT_HOP = 0.2        # seconds — analysis hop (root estimated every 200 ms)
_ROOT_WINDOW = 0.35    # seconds — window size to gather active notes
_ROOT_MIN_SEG = 0.3    # seconds — minimum root segment duration
_ROOT_AMP_FLOOR = 0.15 # amplitude floor for root analysis (lower than melody)
_BASS_BONUS = 0.25     # bonus for roots that match the bass note


def _collect_pitch_classes(
    note_events: list,
    t_start: float,
    t_end: float,
) -> tuple[np.ndarray, int | None]:
    """Collect amplitude-weighted pitch class histogram for a time window.

    Returns (chroma: float[12], bass_pc: int|None).
    chroma[pc] = sum of amplitudes for that pitch class.
    bass_pc = pitch class of the lowest-pitched active note (or None).
    """
    chroma = np.zeros(12, dtype=float)
    lowest_midi = 999
    lowest_pc = None

    for ev in note_events:
        ev_start = float(ev[0])
        ev_end = float(ev[1])
        midi = int(ev[2])
        amp = float(ev[3])

        # Check overlap with window
        overlap_start = max(ev_start, t_start)
        overlap_end = min(ev_end, t_end)
        if overlap_end <= overlap_start:
            continue

        # Weight by overlap fraction of the window
        overlap_frac = (overlap_end - overlap_start) / (t_end - t_start)

        pc = midi % 12
        chroma[pc] += amp * overlap_frac

        if midi < lowest_midi:
            lowest_midi = midi
            lowest_pc = pc

    return chroma, lowest_pc


def _best_root(
    chroma: np.ndarray,
    bass_pc: int | None,
) -> tuple[int, float, str]:
    """Find the root that best explains the active pitch classes.

    Tests all 12 roots against all chord templates.  Scores by:
      - number of template intervals present (weighted by amplitude)
      - bonus if root matches bass note
      - penalty for template intervals that are absent

    Returns (root_pc, confidence, chord_quality).
    """
    if chroma.sum() < 1e-6:
        return 0, 0.0, "maj"

    # Normalise chroma so max = 1
    norm = chroma / (chroma.max() + 1e-9)

    best_root = 0
    best_score = -1.0
    best_quality = "maj"

    for root in range(12):
        for tpl_name, intervals in _CHORD_TEMPLATES.items():
            # Score: sum of chroma values at expected intervals
            hit_energy = 0.0
            miss_count = 0
            for iv in intervals:
                pc = (root + iv) % 12
                if norm[pc] > 0.08:
                    hit_energy += norm[pc]
                else:
                    miss_count += 1

            if miss_count > len(intervals) // 2:
                continue  # too many misses

            # Template weight
            tpl_w = _TEMPLATE_WEIGHTS.get(tpl_name, 0.7)
            # Coverage: fraction of template intervals that are present
            coverage = (len(intervals) - miss_count) / len(intervals)
            score = hit_energy * coverage * tpl_w

            # Bass bonus: if the bass note matches the root
            if bass_pc is not None and bass_pc == root:
                score += _BASS_BONUS

            # Root presence bonus: the root pitch class itself should be strong
            root_strength = norm[root]
            score += root_strength * 0.15

            if score > best_score:
                best_score = score
                best_root = root
                best_quality = tpl_name

    # Confidence: normalise score roughly to 0–1
    # A perfect major triad with strong chroma ≈ 3.0 + bass bonus
    confidence = min(0.99, max(0.1, best_score / 3.5))

    return best_root, confidence, best_quality


def _analyze_roots_pipeline(
    note_events: list,
    effective_key: str,
    audio_duration: float,
) -> dict:
    """Full root-note analysis pipeline.

    1. Filter note events (wider range, lower amplitude floor)
    2. Slide a window across time, collecting pitch-class histograms
    3. For each window, find the best root via chord template matching
    4. Merge consecutive windows with the same root
    5. Filter out very short root segments
    6. Build output in the standard note-sequence format
    """
    # Step 1: light filtering (keep polyphonic content, wider range)
    filtered = []
    for ev in note_events:
        amp = float(ev[3])
        dur = float(ev[1]) - float(ev[0])
        midi = int(ev[2])
        if amp >= _ROOT_AMP_FLOOR and dur >= 0.05 and 28 <= midi <= 96:
            filtered.append(ev)

    if not filtered:
        return {
            "noteSequence": [],
            "solfaSequence": [],
            "confidenceScore": 0.0,
        }

    # Step 2–3: windowed root detection
    raw_roots: list[tuple[float, float, int, float, str]] = []
    # (start, end, root_pc, confidence, quality)

    t = 0.0
    while t < audio_duration:
        w_start = t
        w_end = min(t + _ROOT_WINDOW, audio_duration)

        chroma, bass_pc = _collect_pitch_classes(filtered, w_start, w_end)
        root_pc, conf, quality = _best_root(chroma, bass_pc)

        raw_roots.append((w_start, w_end, root_pc, conf, quality))
        t += _ROOT_HOP

    if not raw_roots:
        return {
            "noteSequence": [],
            "solfaSequence": [],
            "confidenceScore": 0.0,
        }

    # Step 4: merge consecutive windows with the same root
    merged: list[tuple[float, float, int, float, str]] = [raw_roots[0]]
    for seg in raw_roots[1:]:
        prev = merged[-1]
        if seg[2] == prev[2]:
            # Extend, keep weighted average confidence
            prev_dur = prev[1] - prev[0]
            seg_dur = seg[1] - seg[0]
            total_dur = prev_dur + seg_dur
            avg_conf = (prev[3] * prev_dur + seg[3] * seg_dur) / total_dur
            merged[-1] = (prev[0], seg[1], prev[2], avg_conf, prev[4])
        else:
            merged.append(seg)

    # Step 5: filter out very short root segments (passing tones)
    stable: list[tuple[float, float, int, float, str]] = []
    for seg in merged:
        dur = seg[1] - seg[0]
        if dur >= _ROOT_MIN_SEG:
            stable.append(seg)
        elif stable:
            # Absorb short segment into previous
            prev = stable[-1]
            stable[-1] = (prev[0], seg[1], prev[2], prev[3], prev[4])

    if not stable:
        stable = merged[:1] if merged else []

    # Step 6: build output — one "note" per root segment
    note_sequence = []
    solfa_sequence = []
    confidences = []

    for seg in stable:
        root_pc = seg[2]
        root_name = _NOTE_NAMES[root_pc]
        # Use octave 4 as representative (roots are pitch classes, not pitched)
        midi_repr = 60 + root_pc  # C4 = 60
        if root_pc > 6:
            midi_repr = 48 + root_pc  # keep in reasonable range
        frequency = 440.0 * (2 ** ((midi_repr - 69) / 12))
        _, octave, _ = frequency_to_note(frequency)
        solfa = note_to_solfa(root_name, effective_key)

        note_sequence.append({
            "noteName": root_name,
            "octave": octave,
            "startTime": round(seg[0], 3),
            "duration": round(seg[1] - seg[0], 3),
            "frequency": round(frequency, 2),
            "solfa": solfa,
        })
        solfa_sequence.append(solfa)
        confidences.append(seg[3])

    avg_conf = float(np.mean(confidences)) if confidences else 0.0

    return {
        "noteSequence": note_sequence,
        "solfaSequence": solfa_sequence,
        "confidenceScore": round(min(0.99, avg_conf), 3),
    }


# ══════════════════════════════════════════════════════════════════
# ── Public entry point ────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════

def analyze_melody(
    file_path: str,
    selected_key: str = "C",
    start_time: str | None = None,
    end_time: str | None = None,
    song_key: str | None = None,
    starting_note: str | None = None,
    midi_lo: int = MIDI_C3,
    midi_hi: int = MIDI_C6,
    analysis_mode: str = "standard",
) -> dict:
    """
    Analyze a media file.

    Modes:
      - "standard" / "fast": monophonic lead melody extraction
      - "roots": polyphonic harmonic root-note detection
    """
    from basic_pitch.inference import predict
    import soundfile as sf

    start_secs = parse_time_string(start_time)
    end_secs = parse_time_string(end_time)
    wav_path = normalize_audio(file_path, start_secs, end_secs)

    try:
        effective_key = song_key or selected_key or "C"

        if analysis_mode == "roots":
            # ── Root-note pipeline ──
            # Use lower thresholds to capture full polyphonic content
            model_output, _, note_events = predict(
                wav_path,
                onset_threshold=0.4,
                frame_threshold=0.2,
                minimum_note_length=80.0,
            )

            # Get audio duration for windowing
            info = sf.info(wav_path)
            audio_duration = info.duration

            return _analyze_roots_pipeline(note_events, effective_key, audio_duration)

        else:
            # ── Melody pipeline (standard / fast) ──
            p = _get_params(analysis_mode)

            model_output, _, note_events = predict(
                wav_path,
                onset_threshold=p.onset_threshold,
                frame_threshold=p.frame_threshold,
                minimum_note_length=p.minimum_note_length,
            )

            contour = model_output.get("contour")
            if contour is not None:
                contour = np.array(contour)
            else:
                contour = np.zeros((1, _BP_N_CONTOUR_BINS))

            step1 = _filter_events(note_events, midi_lo, midi_hi, p)
            step2 = _select_melody(step1, p)
            step3 = _onset_split(step2, wav_path, p)
            step4 = _refine_pitches(step3, contour, p)
            step5 = _fix_octave_jumps(step4, p)
            step6 = _smooth_pitches(step5, p)
            step7 = _merge_consecutive(step6, p)
            step8 = _cleanup_short_notes(step7, p)

            return _build_output(step8, effective_key)
    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)
