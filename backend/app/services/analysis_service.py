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
  6. Onset-aware note splitting  (fast mode only — detects energy
     onsets inside long notes and splits them)
  7. Median pitch smoothing  (lighter kernel in fast mode)
  8. Consecutive-duplicate merging  (stricter in fast mode)
  9. Short-note cleanup  (removes isolated micro-notes that are not
     musically meaningful, while keeping valid fast phrases)
 10. Build clean note + solfa sequence
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
    onset_energy_threshold: float  # relative energy rise to trigger split

    # Short-note cleanup
    cleanup_min_dur: float       # seconds — notes shorter than this
    cleanup_min_neighbours: int  # must have ≥N notes within window


STANDARD_PARAMS = AnalysisParams(
    # Basic Pitch — default thresholds, conservative
    onset_threshold=0.5,
    frame_threshold=0.3,
    minimum_note_length=127.7,       # ~128 ms (library default)
    # Post-filter
    min_amplitude=0.25,
    min_duration=0.15,               # 150 ms
    melody_window=0.06,              # 60 ms onset grouping
    merge_semitone_tol=1,            # ±1 semitone
    merge_max_gap=0.15,              # 150 ms
    smoothing_window=3,
    # No onset splitting in standard
    onset_split=False,
    onset_energy_threshold=0.0,
    # Cleanup: remove stray micro-notes
    cleanup_min_dur=0.08,
    cleanup_min_neighbours=0,        # disabled for standard
)

FAST_PARAMS = AnalysisParams(
    # Basic Pitch — more sensitive to catch short onsets
    onset_threshold=0.35,
    frame_threshold=0.2,
    minimum_note_length=58.0,        # ~58 ms — let BP emit shorter notes
    # Post-filter — relaxed floors
    min_amplitude=0.18,
    min_duration=0.05,               # 50 ms (vs 150 ms standard)
    melody_window=0.035,             # 35 ms — finer onset grouping
    merge_semitone_tol=0,            # only merge exact same pitch
    merge_max_gap=0.06,              # 60 ms — tighter gap
    smoothing_window=1,              # no smoothing (kernel=1 = identity)
    # Onset splitting enabled
    onset_split=True,
    onset_energy_threshold=1.4,      # 40% energy rise → new note
    # Cleanup: remove isolated stray notes but keep runs
    cleanup_min_dur=0.04,            # 40 ms
    cleanup_min_neighbours=1,        # must have ≥1 neighbour within 0.3 s
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
    """Split long notes at detected energy onsets.

    Uses librosa's onset detection on the original audio to find
    energy transients.  If a note spans an onset, it is split at that
    point — this catches repeated fast notes that Basic Pitch may
    lump into one sustained event.
    """
    if not p.onset_split or not events:
        return events

    try:
        import librosa
    except ImportError:
        return events

    y, sr = librosa.load(wav_path, sr=22050, mono=True)
    onset_frames = librosa.onset.onset_detect(
        y=y, sr=sr, hop_length=256, backtrack=True,
        units="frames",
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=256)

    split: list = []
    for ev in events:
        start = float(ev[0])
        end = float(ev[1])
        midi = int(ev[2])
        amp = float(ev[3])
        rest = ev[4] if len(ev) > 4 else 0.0

        # Find onsets that fall inside this note (with a small margin)
        margin = 0.02  # 20 ms guard to avoid splitting at note edges
        inner = [t for t in onset_times if start + margin < t < end - margin]

        if not inner:
            split.append(ev)
            continue

        # Build sub-notes at each onset boundary
        boundaries = [start] + sorted(inner) + [end]
        for k in range(len(boundaries) - 1):
            seg_start = boundaries[k]
            seg_end = boundaries[k + 1]
            if seg_end - seg_start >= p.min_duration:
                split.append((seg_start, seg_end, midi, amp, rest))

    return split


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
        out.append((ev[0], ev[1], new_midi_int, ev[3],
                     ev[4] if len(ev) > 4 else 0.0))
    return out


def _merge_consecutive(events: list, p: AnalysisParams) -> list:
    """Merge consecutive notes of the same (or very close) pitch.

    In fast mode the tolerance is 0 semitones and the gap threshold is
    tighter, so only truly sustained identical notes are merged.
    """
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
        else:
            merged.append(list(ev))

    return merged


def _cleanup_short_notes(events: list, p: AnalysisParams) -> list:
    """Remove isolated micro-notes that are likely noise.

    A short note is kept if it has at least `cleanup_min_neighbours`
    other notes within a 0.3-second window — this preserves genuine
    fast runs while dropping random isolated blips.
    """
    if p.cleanup_min_neighbours <= 0 or not events:
        return events

    WINDOW = 0.3  # seconds to look for neighbouring notes

    out = []
    starts = [float(ev[0]) for ev in events]

    for idx, ev in enumerate(events):
        dur = float(ev[1]) - float(ev[0])
        if dur >= p.cleanup_min_dur:
            out.append(ev)
            continue

        # Count neighbours within WINDOW
        t = starts[idx]
        neighbours = sum(
            1 for k, s in enumerate(starts)
            if k != idx and abs(s - t) <= WINDOW
        )
        if neighbours >= p.cleanup_min_neighbours:
            out.append(ev)  # part of a fast phrase — keep it

    return out


def _build_output(events: list, effective_key: str) -> dict:
    """Convert cleaned events to the API output format."""
    note_sequence = []
    solfa_sequence = []
    amplitudes = []

    for ev in events:
        ev_start = float(ev[0])
        ev_end = float(ev[1])
        midi_pitch = int(ev[2])
        amplitude = float(ev[3])

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

    if amplitudes:
        avg_amp = float(np.mean(amplitudes))
        confidence = min(0.99, 0.55 + avg_amp * 0.55)
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
        _, _, note_events = predict(
            wav_path,
            onset_threshold=p.onset_threshold,
            frame_threshold=p.frame_threshold,
            minimum_note_length=p.minimum_note_length,
        )

        effective_key = song_key or selected_key or "C"

        # Pipeline
        step1 = _filter_events(note_events, midi_lo, midi_hi, p)
        step2 = _select_melody(step1, p)
        step3 = _onset_split(step2, wav_path, p)
        step4 = _smooth_pitches(step3, p)
        step5 = _merge_consecutive(step4, p)
        step6 = _cleanup_short_notes(step5, p)

        return _build_output(step6, effective_key)
    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)
