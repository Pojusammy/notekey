"""Note-to-solfa mapping service (server-side mirror of frontend utility)."""

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

CHROMATIC_SOLFA = [
    "Do", "Di", "Re", "Ri", "Mi", "Fa",
    "Fi", "Sol", "Si", "La", "Li", "Ti",
]


def note_index(note: str) -> int:
    return NOTE_NAMES.index(note)


def note_to_solfa(note: str, key: str) -> str:
    interval = (note_index(note) - note_index(key)) % 12
    return CHROMATIC_SOLFA[interval]


def frequency_to_note(frequency: float) -> tuple[str, int, float]:
    """Convert frequency to (note_name, octave, cents_offset)."""
    import math

    midi = 12 * math.log2(frequency / 440) + 69
    rounded = round(midi)
    cents = round((midi - rounded) * 100, 1)

    note_idx = rounded % 12
    octave = (rounded // 12) - 1

    return NOTE_NAMES[note_idx], octave, cents
