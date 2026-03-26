"""Melody analysis service — wraps Basic Pitch for note extraction."""

import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from app.services.solfa_service import frequency_to_note, note_to_solfa


def extract_audio_from_video(input_path: str, output_path: str) -> str:
    """Use FFmpeg to extract audio from a video file."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", input_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "22050", "-ac", "1",
            output_path,
        ],
        check=True,
        capture_output=True,
    )
    return output_path


def normalize_audio(input_path: str) -> str:
    """Normalize audio to mono WAV at 22050 Hz for analysis."""
    ext = Path(input_path).suffix.lower()
    video_exts = {".mp4", ".mov", ".webm", ".avi"}

    if ext in video_exts:
        output = tempfile.mktemp(suffix=".wav")
        return extract_audio_from_video(input_path, output)

    if ext == ".wav":
        return input_path

    # Convert other audio formats to WAV
    output = tempfile.mktemp(suffix=".wav")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", input_path,
            "-acodec", "pcm_s16le", "-ar", "22050", "-ac", "1",
            output,
        ],
        check=True,
        capture_output=True,
    )
    return output


def analyze_melody(file_path: str, selected_key: str = "C") -> dict:
    """
    Analyze a media file and extract the melodic line.

    Returns a dict with noteSequence, solfaSequence, and confidenceScore.
    """
    from basic_pitch.inference import predict

    # Normalize to WAV
    wav_path = normalize_audio(file_path)

    # Run Basic Pitch inference
    model_output, midi_data, note_events = predict(wav_path)

    # note_events is a list of (start_time, end_time, pitch_midi, amplitude, pitch_bend)
    note_sequence = []
    solfa_sequence = []

    for event in note_events:
        start_time = float(event[0])
        end_time = float(event[1])
        midi_pitch = int(event[2])
        amplitude = float(event[3])

        # Convert MIDI to frequency
        frequency = 440.0 * (2 ** ((midi_pitch - 69) / 12))
        note_name, octave, cents = frequency_to_note(frequency)
        solfa = note_to_solfa(note_name, selected_key)

        note_sequence.append({
            "noteName": note_name,
            "octave": octave,
            "startTime": round(start_time, 3),
            "duration": round(end_time - start_time, 3),
            "frequency": round(frequency, 2),
            "solfa": solfa,
        })
        solfa_sequence.append(solfa)

    # Clean up temp file if created
    if wav_path != file_path and os.path.exists(wav_path):
        os.unlink(wav_path)

    confidence = float(np.mean([e[3] for e in note_events])) if note_events else 0.0

    return {
        "noteSequence": note_sequence,
        "solfaSequence": solfa_sequence,
        "confidenceScore": round(confidence, 3),
    }
