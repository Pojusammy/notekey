"""Melody analysis service — wraps Basic Pitch for note extraction."""

import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from app.services.solfa_service import frequency_to_note, note_to_solfa


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

    # Input seeking (fast seek before -i)
    if start_time is not None and start_time > 0:
        cmd += ["-ss", str(start_time)]

    cmd += ["-i", input_path]

    # Duration limit
    if end_time is not None and start_time is not None:
        duration = end_time - start_time
        if duration > 0:
            cmd += ["-t", str(duration)]
    elif end_time is not None:
        cmd += ["-t", str(end_time)]

    cmd += [
        "-vn",                    # strip video
        "-acodec", "pcm_s16le",  # 16-bit PCM
        "-ar", "22050",          # 22050 Hz
        "-ac", "1",              # mono
        output,
    ]

    subprocess.run(cmd, check=True, capture_output=True)
    return output


def analyze_melody(
    file_path: str,
    selected_key: str = "C",
    start_time: str | None = None,
    end_time: str | None = None,
    song_key: str | None = None,
    starting_note: str | None = None,
) -> dict:
    """
    Analyze a media file and extract the melodic line.

    Args:
        file_path: Path to the uploaded audio/video file.
        selected_key: The global key selected in the navbar.
        start_time: Optional start time string (MM:SS or seconds).
        end_time: Optional end time string (MM:SS or seconds).
        song_key: Optional song key override for solfa mapping.
        starting_note: Optional starting note hint (unused by Basic Pitch
                       but reserved for future post-processing).

    Returns:
        Dict with noteSequence, solfaSequence, and confidenceScore.
    """
    from basic_pitch.inference import predict

    # Parse time range
    start_secs = parse_time_string(start_time)
    end_secs = parse_time_string(end_time)

    # Normalize to WAV (with optional trim)
    wav_path = normalize_audio(file_path, start_secs, end_secs)

    try:
        # Run Basic Pitch inference
        model_output, midi_data, note_events = predict(wav_path)

        # Use song key if provided, otherwise fall back to selected key
        effective_key = song_key or selected_key or "C"

        # note_events is a list of (start_time, end_time, pitch_midi, amplitude, pitch_bend)
        note_sequence = []
        solfa_sequence = []

        for event in note_events:
            ev_start = float(event[0])
            ev_end = float(event[1])
            midi_pitch = int(event[2])
            amplitude = float(event[3])

            # Convert MIDI to frequency
            frequency = 440.0 * (2 ** ((midi_pitch - 69) / 12))
            note_name, octave, cents = frequency_to_note(frequency)
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

        confidence = (
            float(np.mean([e[3] for e in note_events]))
            if note_events
            else 0.0
        )

        return {
            "noteSequence": note_sequence,
            "solfaSequence": solfa_sequence,
            "confidenceScore": round(min(0.99, max(0.5, confidence)), 3),
        }
    finally:
        # Clean up temp WAV
        if os.path.exists(wav_path):
            os.unlink(wav_path)
