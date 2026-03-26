import { create } from "zustand";
import type { DetectedNote } from "@/types/music";

interface DetectorStore {
  isListening: boolean;
  currentNote: DetectedNote | null;
  setListening: (listening: boolean) => void;
  setCurrentNote: (note: DetectedNote | null) => void;
}

export const useDetectorStore = create<DetectorStore>()((set) => ({
  isListening: false,
  currentNote: null,
  setListening: (listening) => set({ isListening: listening }),
  setCurrentNote: (note) => set({ currentNote: note }),
}));
