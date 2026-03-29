"""
MIR Pipeline — Demucs + chroma-based chord detection.

Replaces the Basic Pitch-only roots analysis with a proper source-separation
pipeline that correctly handles:
  - Root note detection (harmonic stem, not full mix)
  - Chord inversions (C/E etc.) via separate bass stem
  - Syncopated instrumentals via onset-aware segmentation
  - Full polyphonic instrumentals

Pipeline:
  wav → estimate_tuning
      → separate_stems (Demucs htdemucs)
      → extract chroma_cqt (harmonic stem + bass stem independently)
      → detect BPM → adaptive hop_length
      → onset boundaries (harmonic stem)
      → segment chroma by onsets
      → template-match each segment → root + quality + bass note
      → merge consecutive identical chords
      → filter short segments
      → API-format output

Entry point: analyze_chords(wav_path, effective_key) → dict
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import librosa
import soundfile as sf

# ── Note names (chromatic) ────────────────────────────────────────
_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# ── Sample rate (matches normalize_audio output) ──────────────────
_SR = 22050

# ── Chord templates: binary interval vector from root ─────────────
# Index = semitone interval from root.  1 = present, 0 = absent.
_CHORD_TEMPLATES: dict[str, list[int]] = {
    "maj":   [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0],
    "min":   [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0],
    "7":     [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0],
    "maj7":  [1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1],
    "min7":  [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0],
    "dim":   [1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0],
    "dim7":  [1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0],
    "aug":   [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
    "sus4":  [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0],
    "sus2":  [1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0],
    "add9":  [1, 0, 1, 0, 1, 0, 0, 1, 0, 0, 0, 0],
    "6":     [1, 0, 0, 0, 1, 0, 0, 1, 0, 1, 0, 0],
    "min6":  [1, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0],
    "9":     [1, 0, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0],
    "min9":  [1, 0, 1, 1, 0, 0, 0, 1, 0, 0, 1, 0],
    "power": [1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0],
}

# Template quality weights: prefer triads over ambiguous extended chords
_TEMPLATE_WEIGHTS: dict[str, float] = {
    "maj": 1.0, "min": 1.0, "7": 0.95, "maj7": 0.9, "min7": 0.9,
    "dim": 0.8, "dim7": 0.8, "aug": 0.8, "sus4": 0.75, "sus2": 0.75,
    "add9": 0.85, "6": 0.85, "min6": 0.85, "9": 0.85, "min9": 0.85,
    "power": 0.6,
}

# Minimum chord segment duration (seconds) — shorter = passing tone
_MIN_CHORD_DUR = 0.25

# Onset detection sensitivity — lower = more onsets detected
_ONSET_DELTA = 0.3


# ─────────────────────────────────────────────────────────────────
# Stage 1: Tuning estimation
# ─────────────────────────────────────────────────────────────────

def _estimate_tuning(y: np.ndarray) -> float:
    """
    Estimate tuning deviation in fractional semitones.
    A guitar tuned to A=432 Hz returns ~ -0.31 semitones.
    This is passed to chroma_cqt(tuning=...) to correct the bins.
    """
    try:
        return float(librosa.estimate_tuning(y=y, sr=_SR))
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────
# Stage 2: Stem separation via Demucs
# ─────────────────────────────────────────────────────────────────

def separate_stems(audio_path: str, out_dir: str) -> dict[str, str]:
    """
    Run Demucs (htdemucs model) to separate bass and harmonic stems.

    Why bass separation matters:
      A C/E chord has E as the lowest note. Without stem separation,
      chroma on the full mix finds E as dominant and misidentifies the
      chord as Em. By isolating the bass, we detect E independently
      from the harmonic root (C), then combine as C/E.

    Returns:
      {"bass": "/path/bass.wav", "harmonic": "/path/other.wav"}

    Falls back to {"bass": audio_path, "harmonic": audio_path} if
    Demucs fails (e.g. not installed), so the pipeline degrades
    gracefully without inversion support rather than crashing.
    """
    track_name = Path(audio_path).stem
    bass_path    = os.path.join(out_dir, "htdemucs", track_name, "bass.wav")
    other_path   = os.path.join(out_dir, "htdemucs", track_name, "other.wav")

    try:
        subprocess.run(
            [
                "python", "-m", "demucs",
                "--model", "htdemucs",
                "--out", out_dir,
                audio_path,
            ],
            check=True,
            capture_output=True,
            timeout=600,          # 10-minute ceiling for a long track on CPU
        )

        if os.path.exists(bass_path) and os.path.exists(other_path):
            return {"bass": bass_path, "harmonic": other_path}

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        # Demucs not installed or failed — use full mix for both stems.
        # Root detection will still work; only inversion detection degrades.
        pass

    return {"bass": audio_path, "harmonic": audio_path}


# ─────────────────────────────────────────────────────────────────
# Stage 3: Chroma feature extraction
# ─────────────────────────────────────────────────────────────────

def _extract_chroma(audio_path: str, hop_length: int, tuning: float) -> tuple[np.ndarray, np.ndarray]:
    """
    Load audio and return (y, chroma_cqt).

    Why chroma_cqt over STFT chroma:
      CQT is logarithmically spaced, matching music's pitch structure.
      bins_per_octave=36 gives 3 bins per semitone — enough sub-semitone
      resolution to survive a ±30 cent tuning deviation without aliasing.

    Why L2 norm per frame:
      Normalisation removes loudness variation so that quiet chords score
      identically to loud ones — critical for dynamic music.
    """
    y, _ = librosa.load(audio_path, sr=_SR, mono=True)
    chroma = librosa.feature.chroma_cqt(
        y=y,
        sr=_SR,
        hop_length=hop_length,
        bins_per_octave=36,
        tuning=tuning,
        norm=2,              # L2 per frame
    )
    return y, chroma          # y shape: (N,)  chroma shape: (12, T)


# ─────────────────────────────────────────────────────────────────
# Stage 4: Adaptive hop length from BPM
# ─────────────────────────────────────────────────────────────────

def _adaptive_hop(y: np.ndarray) -> tuple[int, float]:
    """
    Set hop_length to ~1/4 beat duration so each 16th note gets
    at least one analysis frame — essential for syncopated passages.

    Returns (hop_length_samples, bpm).
    """
    try:
        tempo, _ = librosa.beat.beat_track(y=y, sr=_SR)
        bpm = float(tempo) if np.isscalar(tempo) else float(np.atleast_1d(tempo)[0])
        bpm = max(40.0, min(240.0, bpm))
    except Exception:
        bpm = 120.0

    # 16th note duration in samples
    beat_samples = (_SR * 60.0) / bpm
    sixteenth = beat_samples / 4.0
    hop = int(sixteenth)
    return max(64, min(512, hop)), bpm


# ─────────────────────────────────────────────────────────────────
# Stage 5: Onset-aware segmentation
# ─────────────────────────────────────────────────────────────────

def _onset_frames(y_harm: np.ndarray, hop_length: int) -> np.ndarray:
    """
    Detect harmonic-change boundaries in the harmonic stem.

    backtrack=True snaps each onset to the energy valley just before
    the attack peak — gives sharper boundaries for chord changes.
    """
    onset_env = librosa.onset.onset_strength(y=y_harm, sr=_SR, hop_length=hop_length)
    onsets = librosa.onset.onset_detect(
        onset_envelope=onset_env,
        sr=_SR,
        hop_length=hop_length,
        units="frames",
        backtrack=True,
        delta=_ONSET_DELTA,
    )
    return onsets


def _segment_chroma(
    chroma_harm: np.ndarray,
    chroma_bass: np.ndarray,
    onsets: np.ndarray,
    T: int,
) -> list[tuple[int, int, np.ndarray, np.ndarray]]:
    """
    Average chroma within each onset segment.

    Why: A single frame is too noisy for chord ID; averaging over the
    stable region between two onset boundaries gives a much cleaner
    pitch-class histogram.

    Returns list of (start_frame, end_frame, harm_chroma_12, bass_chroma_12).
    """
    boundaries = sorted(set([0] + list(onsets) + [T]))
    segments = []
    for i in range(len(boundaries) - 1):
        s, e = boundaries[i], boundaries[i + 1]
        if e > s:
            harm = chroma_harm[:, s:e].mean(axis=1)   # (12,)
            bass = chroma_bass[:, s:e].mean(axis=1)   # (12,)
            segments.append((s, e, harm, bass))
    return segments


# ─────────────────────────────────────────────────────────────────
# Stage 6: Template matching per segment
# ─────────────────────────────────────────────────────────────────

def _match_segment(
    harm_chroma: np.ndarray,
    bass_chroma: np.ndarray,
) -> tuple[int, str, int, float]:
    """
    Match a chroma frame against all chord templates × all 12 roots.

    Score = cosine_similarity(chroma, rotated_template) × template_weight

    The harmonic stem gives the chord root + quality.
    The bass stem gives the bass note independently.
    If root ≠ bass → slash chord (inversion).

    Returns (root_idx 0-11, quality, bass_idx 0-11, confidence 0-1).
    """
    best_score = -1.0
    best_root = 0
    best_quality = "maj"

    harm_norm = np.linalg.norm(harm_chroma)
    if harm_norm < 1e-8:
        return 0, "maj", 0, 0.0

    harm_unit = harm_chroma / harm_norm

    for quality, template in _CHORD_TEMPLATES.items():
        t_vec = np.array(template, dtype=float)
        t_norm = np.linalg.norm(t_vec)
        if t_norm < 1e-8:
            continue
        t_unit = t_vec / t_norm

        for root in range(12):
            rotated = np.roll(t_unit, root)
            score = float(np.dot(harm_unit, rotated))
            score *= _TEMPLATE_WEIGHTS.get(quality, 0.7)

            if score > best_score:
                best_score = score
                best_root = root
                best_quality = quality

    # Bass note: highest-energy pitch class in the bass stem
    bass_norm = np.linalg.norm(bass_chroma)
    if bass_norm > 1e-8:
        bass_idx = int(np.argmax(bass_chroma))
    else:
        bass_idx = best_root   # no bass info → assume root position

    confidence = float(min(0.99, max(0.0, best_score)))
    return best_root, best_quality, bass_idx, confidence


# ─────────────────────────────────────────────────────────────────
# Stage 7: Merge + filter chord events
# ─────────────────────────────────────────────────────────────────

def _build_chord_events(
    segments: list[tuple[int, int, np.ndarray, np.ndarray]],
    hop_length: int,
) -> list[dict]:
    """
    1. Match each segment to a chord.
    2. Merge consecutive frames with the same root + quality.
    3. Drop segments shorter than _MIN_CHORD_DUR (passing tones),
       absorbing them into the previous chord.

    Returns list of chord dicts with start/end times.
    """
    if not segments:
        return []

    raw: list[dict] = []
    for s_frame, e_frame, harm_chroma, bass_chroma in segments:
        root_idx, quality, bass_idx, conf = _match_segment(harm_chroma, bass_chroma)

        start_t = float(librosa.frames_to_time(s_frame, sr=_SR, hop_length=hop_length))
        end_t   = float(librosa.frames_to_time(e_frame, sr=_SR, hop_length=hop_length))

        root_name = _NOTE_NAMES[root_idx]
        bass_name = _NOTE_NAMES[bass_idx]

        # Build chord symbol
        if bass_idx != root_idx:
            chord_symbol = f"{root_name}{quality}/{bass_name}"
        else:
            chord_symbol = f"{root_name}{quality}"

        raw.append({
            "root_idx":  root_idx,
            "root":      root_name,
            "quality":   quality,
            "bass":      bass_name,
            "chord":     chord_symbol,
            "start":     start_t,
            "end":       end_t,
            "confidence": conf,
        })

    if not raw:
        return []

    # Merge consecutive same-chord segments
    merged: list[dict] = [dict(raw[0])]
    for seg in raw[1:]:
        prev = merged[-1]
        same_chord = (
            seg["root_idx"] == prev["root_idx"]
            and seg["quality"] == prev["quality"]
        )
        if same_chord:
            prev["end"] = seg["end"]
            # Running average confidence
            w1 = prev["end"] - prev["start"]
            w2 = seg["end"] - seg["start"]
            total = w1 + w2
            if total > 0:
                prev["confidence"] = (prev["confidence"] * w1 + seg["confidence"] * w2) / total
        else:
            merged.append(dict(seg))

    # Filter short segments (absorb into neighbour)
    stable: list[dict] = []
    for seg in merged:
        dur = seg["end"] - seg["start"]
        if dur >= _MIN_CHORD_DUR:
            stable.append(seg)
        elif stable:
            stable[-1]["end"] = seg["end"]   # absorb into previous

    # If filtering removed everything, return longest segment
    if not stable and merged:
        merged.sort(key=lambda s: s["end"] - s["start"], reverse=True)
        stable = merged[:1]

    return stable


# ─────────────────────────────────────────────────────────────────
# Stage 8: Format for API response
# ─────────────────────────────────────────────────────────────────

def _build_output(chord_events: list[dict], effective_key: str) -> dict:
    """
    Convert chord events to the standard noteSequence API format.

    noteName  = chord root (e.g. "C", "F#")
    octave    = 4 (chords are pitch-class, not pitched — pick middle octave)
    frequency = root note frequency (representative)
    solfa     = full chord symbol (e.g. "Cmaj", "G7/B", "Fmin7")

    The solfa field carries the chord symbol rather than solfège because
    the frontend uses this field to display the chord name in chord mode.
    """
    from app.services.solfa_service import frequency_to_note

    note_sequence = []
    solfa_sequence = []
    confidences = []

    for ev in chord_events:
        root_pc = ev["root_idx"]
        # Representative MIDI: C4=60, keep all roots in octave 4/5 range
        midi_repr = 60 + root_pc if root_pc <= 6 else 48 + root_pc
        frequency = 440.0 * (2 ** ((midi_repr - 69) / 12))
        _, octave, _ = frequency_to_note(frequency)

        chord_symbol = ev["chord"]

        note_sequence.append({
            "noteName": ev["root"],
            "octave":    octave,
            "startTime": round(ev["start"], 3),
            "duration":  round(ev["end"] - ev["start"], 3),
            "frequency": round(frequency, 2),
            "solfa":     chord_symbol,
        })
        solfa_sequence.append(chord_symbol)
        confidences.append(ev["confidence"])

    avg_conf = float(np.mean(confidences)) if confidences else 0.0

    return {
        "noteSequence":   note_sequence,
        "solfaSequence":  solfa_sequence,
        "confidenceScore": round(min(0.99, avg_conf), 3),
    }


# ─────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────

def analyze_chords(wav_path: str, effective_key: str = "C") -> dict:
    """
    Full MIR chord analysis pipeline.

    Args:
        wav_path:      Path to a mono 22050 Hz WAV file (output of normalize_audio).
        effective_key: The song key (e.g. "G") used for solfa mapping.

    Returns:
        API-format dict: {noteSequence, solfaSequence, confidenceScore}
    """
    stems_dir = tempfile.mkdtemp(prefix="demucs_")

    try:
        # ── 1. Load audio + estimate tuning ──────────────────────────
        y, _ = librosa.load(wav_path, sr=_SR, mono=True)
        tuning = _estimate_tuning(y)

        # ── 2. Stem separation ────────────────────────────────────────
        stems = separate_stems(wav_path, stems_dir)

        # ── 3. BPM → adaptive hop length ─────────────────────────────
        hop_length, _bpm = _adaptive_hop(y)

        # ── 4. Chroma extraction (harmonic + bass independently) ──────
        y_harm, chroma_harm = _extract_chroma(stems["harmonic"], hop_length, tuning)
        _,      chroma_bass = _extract_chroma(stems["bass"],     hop_length, tuning)

        # Align lengths in case Demucs output differs by a frame
        T = min(chroma_harm.shape[1], chroma_bass.shape[1])
        chroma_harm = chroma_harm[:, :T]
        chroma_bass = chroma_bass[:, :T]

        if T == 0:
            return {"noteSequence": [], "solfaSequence": [], "confidenceScore": 0.0}

        # ── 5. Onset-aware segmentation ───────────────────────────────
        onsets = _onset_frames(y_harm, hop_length)
        segments = _segment_chroma(chroma_harm, chroma_bass, onsets, T)

        if not segments:
            return {"noteSequence": [], "solfaSequence": [], "confidenceScore": 0.0}

        # ── 6–7. Match + merge chord events ──────────────────────────
        chord_events = _build_chord_events(segments, hop_length)

        if not chord_events:
            return {"noteSequence": [], "solfaSequence": [], "confidenceScore": 0.0}

        # ── 8. Format output ──────────────────────────────────────────
        return _build_output(chord_events, effective_key)

    finally:
        # Clean up Demucs stems (can be several hundred MB per track)
        try:
            shutil.rmtree(stems_dir, ignore_errors=True)
        except Exception:
            pass
