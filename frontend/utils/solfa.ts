import {
  NOTE_NAMES,
  type NoteName,
  MAJOR_SCALE_INTERVALS,
  MAJOR_SOLFA,
} from "@/types/music";

/**
 * Map of all 12 chromatic semitones to their solfa name
 * relative to a given key. Notes outside the major scale
 * get sharped names (Di, Ri, Fi, Si, Li).
 */
const CHROMATIC_SOLFA = [
  "Do",  // 0
  "Di",  // 1  (raised Do / flat Re)
  "Re",  // 2
  "Ri",  // 3  (raised Re / flat Mi)
  "Mi",  // 4
  "Fa",  // 5
  "Fi",  // 6  (raised Fa / flat Sol)
  "Sol", // 7
  "Si",  // 8  (raised Sol / flat La)
  "La",  // 9
  "Li",  // 10 (raised La / flat Ti)
  "Ti",  // 11
] as const;

/**
 * Get the index of a note name in the chromatic scale (C = 0).
 */
export function noteIndex(note: NoteName): number {
  return NOTE_NAMES.indexOf(note);
}

/**
 * Get the semitone interval from the key root to the given note.
 */
export function semitonesFromKey(note: NoteName, key: NoteName): number {
  const diff = noteIndex(note) - noteIndex(key);
  return ((diff % 12) + 12) % 12;
}

/**
 * Convert a note name to its tonic solfa relative to a key.
 */
export function noteToSolfa(note: NoteName, key: NoteName): string {
  const interval = semitonesFromKey(note, key);
  return CHROMATIC_SOLFA[interval];
}

/**
 * Check if a note is in the major scale of the given key.
 */
export function isInMajorScale(note: NoteName, key: NoteName): boolean {
  const interval = semitonesFromKey(note, key);
  return (MAJOR_SCALE_INTERVALS as readonly number[]).includes(interval);
}

/**
 * Get all notes in the major scale of a given key.
 */
export function getMajorScaleNotes(key: NoteName): NoteName[] {
  const keyIdx = noteIndex(key);
  return MAJOR_SCALE_INTERVALS.map(
    (interval) => NOTE_NAMES[(keyIdx + interval) % 12]
  );
}

/**
 * Get the major scale with solfa labels for a given key.
 */
export function getMajorScaleWithSolfa(
  key: NoteName
): { note: NoteName; solfa: string }[] {
  const notes = getMajorScaleNotes(key);
  return notes.map((note, i) => ({
    note,
    solfa: MAJOR_SOLFA[i],
  }));
}

/**
 * Convert a frequency (Hz) to the nearest note name, octave, and cents offset.
 */
export function frequencyToNote(frequency: number): {
  noteName: NoteName;
  octave: number;
  centsOffset: number;
} {
  // A4 = 440 Hz, MIDI note 69
  const midiNote = 12 * Math.log2(frequency / 440) + 69;
  const roundedMidi = Math.round(midiNote);
  const centsOffset = Math.round((midiNote - roundedMidi) * 100);

  const noteIdx = ((roundedMidi % 12) + 12) % 12;
  const octave = Math.floor(roundedMidi / 12) - 1;

  return {
    noteName: NOTE_NAMES[noteIdx],
    octave,
    centsOffset,
  };
}

/**
 * Convert a note name + octave to frequency.
 */
export function noteToFrequency(note: NoteName, octave: number): number {
  const midiNote = (octave + 1) * 12 + noteIndex(note);
  return 440 * Math.pow(2, (midiNote - 69) / 12);
}
