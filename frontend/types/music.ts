export const NOTE_NAMES = [
  "C",
  "C#",
  "D",
  "D#",
  "E",
  "F",
  "F#",
  "G",
  "G#",
  "A",
  "A#",
  "B",
] as const;

export type NoteName = (typeof NOTE_NAMES)[number];

export const SOLFA_NAMES = [
  "Do",
  "Di",
  "Re",
  "Ri",
  "Mi",
  "Fa",
  "Fi",
  "Sol",
  "Si",
  "La",
  "Li",
  "Ti",
] as const;

export type SolfaName = (typeof SOLFA_NAMES)[number];

export const MAJOR_SCALE_INTERVALS = [0, 2, 4, 5, 7, 9, 11] as const;

export const MAJOR_SOLFA: SolfaName[] = [
  "Do",
  "Re",
  "Mi",
  "Fa",
  "Sol",
  "La",
  "Ti",
];

export interface DetectedNote {
  noteName: NoteName;
  octave: number;
  frequency: number;
  centsOffset: number;
  solfa: string;
  confidence: number;
}

export interface NoteEvent {
  noteName: NoteName;
  octave: number;
  startTime: number;
  duration: number;
  frequency: number;
  solfa: string;
}

export interface AnalysisResult {
  id: string;
  jobId: string;
  noteSequence: NoteEvent[];
  solfaSequence: string[];
  key: NoteName;
  confidenceScore: number;
  createdAt: string;
}

export interface AnalysisJob {
  id: string;
  userId: string;
  jobType: "note_detection" | "recording_analysis";
  inputFileUrl?: string;
  selectedKey: NoteName;
  status: "pending" | "processing" | "completed" | "failed";
  createdAt: string;
  completedAt?: string;
  errorMessage?: string;
}

export interface SavedSession {
  id: string;
  userId: string;
  title: string;
  resultId: string;
  result?: AnalysisResult;
  createdAt: string;
}
