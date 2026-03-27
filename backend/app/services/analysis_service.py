"""Melody analysis service — wraps Basic Pitch for note extraction.

Extracts only the predominant monophonic melodic line by applying:
  1. Pitch-range gating  (default C3–C6, configurable)
  2. Amplitude / confidence filtering
  3. Minimum-duration gating  (~150 ms)
  4. Monophonic melody selection  (loudest in mid-high range per window)
  5. Median pitch smoothing  (removes jitter / rapid switching)
  6. Consecutive-duplicate merging  (vibrato tolerance ±1 semitone)
  7. Continuity preference  (among equal-amplitude candidates, prefer
     the note closest in pitch to the previous one)
"""

import os
import subprocess
import tempfile

import numpy as np

from app.services.solfa_service import frequency_to_note, note_to_solfa

# ── Configurable constants ──────────────────────────────────────────
MIDI_C3 = 48          # lower bound of melody range
MIDI_C6 = 84          # upper bound of melody range
MIN_AMPLITUDE = 0.25  # discard quiet harmonics / noise
MIN_DURATION = 0.15   # ignore notes shorter than 150 ms
MELODY_WINDOW = 0.06  # treat onsets within 60 ms as simultaneous
MERGE_SEMITONE_TOL = 1  # merge consecutive notes within ±1 semitone
SMOOTHING_WINDOW = 3  # median-filter kernel size for pitch smoothing


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


# ── Internal helpers ────────────────────────────────────────────────

def _filter_events(note_events: list, midi_lo: int, midi_hi: int) -> list:
    """Step 1-2: pitch-range + amplitude + duration gating."""
    out = []
    for ev in note_events:
        midi = int(ev[2])
        amp = float(ev[3])
        dur = float(ev[1]) - float(ev[0])
        if midi_lo <= midi <= midi_hi and amp >= MIN_AMPLITUDE and dur >= MIN_DURATION:
            out.append(ev)
    return out


def _select_melody(events: list) -> list:
    """Step 3: monophonic melody extraction.

    For each onset window keep a single note.  Among candidates prefer
    mid-high pitches (bias = +amp * 0.15 per octave above C4) and,
    when amplitudes are close, the note nearest in pitch to the
    previous selection (continuity).
    """
    events.sort(key=lambda e: (float(e[0]), -float(e[3])))

    melody: list = []
    prev_midi: float | None = None
    i = 0

    while i < len(events):
        t0 = float(events[i][0])
        group = [events[i]]
        j = i + 1
        while j < len(events) and float(events[j][0]) - t0 < MELODY_WINDOW:
            group.append(events[j])
            j += 1

        def _score(ev):
            midi = int(ev[2])
            amp = float(ev[3])
            # Bias toward mid-high range (melody lives above bass)
            octave_above_c4 = (midi - 60) / 12.0
            range_bias = max(0.0, octave_above_c4 * 0.15)
            # Continuity bonus: prefer notes close to previous
            cont_bonus = 0.0
            if prev_midi is not None:
                semitone_dist = abs(midi - prev_midi)
                cont_bonus = max(0.0, 0.2 - semitone_dist * 0.015)
            return amp + range_bias + cont_bonus

        best = max(group, key=_score)
        melody.append(best)
        prev_midi = int(best[2])
        i = j

    return melody


def _smooth_pitches(events: list) -> list:
    """Step 4: median-filter pitch sequence to remove jitter.

    Replaces each MIDI pitch with the median of a sliding window,
    snapping back to the nearest original candidate when the median
    falls between semitones.
    """
    if len(events) <= SMOOTHING_WINDOW:
        return events

    midis = np.array([int(e[2]) for e in events], dtype=float)
    half = SMOOTHING_WINDOW // 2
    smoothed_midis = midis.copy()

    for idx in range(len(midis)):
        lo = max(0, idx - half)
        hi = min(len(midis), idx + half + 1)
        smoothed_midis[idx] = round(float(np.median(midis[lo:hi])))

    out = []
    for ev, new_midi in zip(events, smoothed_midis):
        new_midi_int = int(new_midi)
        # Rebuild tuple with smoothed pitch
        out.append((ev[0], ev[1], new_midi_int, ev[3],
                     ev[4] if len(ev) > 4 else 0.0))
    return out


def _merge_consecutive(events: list) -> list:
    """Step 5: merge consecutive notes of the same (or very close) pitch.

    Two adjacent notes are merged when their MIDI pitches differ by at
    most MERGE_SEMITONE_TOL semitones.  The merged note inherits the
    start of the first, the end of the last, and the max amplitude.
    """
    if not events:
        return events

    merged: list = [list(events[0])]

    for ev in events[1:]:
        prev = merged[-1]
        prev_midi = int(prev[2])
        cur_midi = int(ev[2])
        gap = float(ev[0]) - float(prev[1])

        if abs(cur_midi - prev_midi) <= MERGE_SEMITONE_TOL and gap < 0.15:
            # Extend duration, keep higher amplitude, keep pitch of louder note
            prev[1] = ev[1]  # extend end time
            if float(ev[3]) > float(prev[3]):
                prev[2] = ev[2]  # adopt pitch of louder segment
                prev[3] = ev[3]
        else:
            merged.append(list(ev))

    return merged


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


# ── Public entry point ──────────────────────────────────────────────

def analyze_melody(
    file_path: str,
    selected_key: str = "C",
    start_time: str | None = None,
    end_time: str | None = None,
    song_key: str | None = None,
    starting_note: str | None = None,
    midi_lo: int = MIDI_C3,
    midi_hi: int = MIDI_C6,
) -> dict:
    """
    Analyze a media file and extract the predominant melodic line.

    Pipeline:
      Basic Pitch → pitch-range gate → amplitude/duration gate →
      monophonic selection → median pitch smoothing → merge duplicates →
      build clean note + solfa sequence.

    Args:
        file_path:      Path to the uploaded audio/video file.
        selected_key:   Global key from the navbar.
        start_time:     Optional start time (MM:SS or seconds).
        end_time:       Optional end time (MM:SS or seconds).
        song_key:       Optional song key override for solfa mapping.
        starting_note:  Reserved for future post-processing.
        midi_lo:        Lowest MIDI note to accept (default C3 = 48).
        midi_hi:        Highest MIDI note to accept (default C6 = 84).
    """
    from basic_pitch.inference import predict

    start_secs = parse_time_string(start_time)
    end_secs = parse_time_string(end_time)

    wav_path = normalize_audio(file_path, start_secs, end_secs)

    try:
        _, _, note_events = predict(wav_path)

        effective_key = song_key or selected_key or "C"

        # Pipeline
        step1 = _filter_events(note_events, midi_lo, midi_hi)
        step2 = _select_melody(step1)
        step3 = _smooth_pitches(step2)
        step4 = _merge_consecutive(step3)

        return _build_output(step4, effective_key)
    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)
