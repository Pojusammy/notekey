"""Melody analysis service — wraps Basic Pitch for note extraction.

Supports two analysis modes:

**Standard mode** (default):
  Conservative filtering tuned for clean, stable melody output.
  Good for sustained vocals, slow melodies, and general use.

**Fast mode** (`analysis_mode="fast"`):
  Optimised for interludes, runs, syncopation, and quick lead-note
  passages.  Uses lower thresholds at every pipeline stage so short,
  valid melodic notes are preserved rather than merged or discarded.

Pipeline (both modes share the same stages):
  1. Basic Pitch inference  (onset/frame thresholds + min note length
     are mode-dependent)
  2. Pitch-range gating  (C3–C6, configurable)
  3. Amplitude / confidence filtering
  4. Minimum-duration gating
  5. Monophonic melody selection  (onset window is mode-dependent)
  6. Onset-aware note splitting  (fast mode only)
  7. **Contour-based pitch refinement**  (NEW — re-estimates pitch from
     stable middle frames of BP's raw contour output, weighted median,
     cents-aware quantization, per-note confidence)
  8. **Octave sanity correction**  (NEW — fixes implausible octave jumps
     using melodic context)
  9. Median pitch smoothing  (lighter kernel in fast mode)
 10. Consecutive-duplicate merging
 11. Short-note cleanup
 12. Build clean note + solfa sequence  (confidence now per-note aware)
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


# ── Public entry point ────────────────────────────────────────────

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
    Analyze a media file and extract the predominant melodic line.

    Args:
        file_path:      Path to the uploaded audio/video file.
        selected_key:   Global key from the navbar.
        start_time:     Optional start time (MM:SS or seconds).
        end_time:       Optional end time (MM:SS or seconds).
        song_key:       Optional song key override for solfa mapping.
        starting_note:  Reserved for future post-processing.
        midi_lo:        Lowest MIDI note to accept (default C3 = 48).
        midi_hi:        Highest MIDI note to accept (default C6 = 84).
        analysis_mode:  "standard" (default) or "fast" for interludes/runs.
    """
    from basic_pitch.inference import predict

    p = _get_params(analysis_mode)

    start_secs = parse_time_string(start_time)
    end_secs = parse_time_string(end_time)

    wav_path = normalize_audio(file_path, start_secs, end_secs)

    try:
        model_output, _, note_events = predict(
            wav_path,
            onset_threshold=p.onset_threshold,
            frame_threshold=p.frame_threshold,
            minimum_note_length=p.minimum_note_length,
        )

        # Extract contour matrix for pitch refinement
        contour = model_output.get("contour")
        if contour is not None:
            contour = np.array(contour)
        else:
            contour = np.zeros((1, _BP_N_CONTOUR_BINS))

        effective_key = song_key or selected_key or "C"

        # Pipeline
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
