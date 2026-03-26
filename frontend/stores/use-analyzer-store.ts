import { create } from "zustand";
import type { AnalysisJob, AnalysisResult } from "@/types/music";

interface AnalyzerStore {
  currentJob: AnalysisJob | null;
  currentResult: AnalysisResult | null;
  isUploading: boolean;
  uploadProgress: number;
  setCurrentJob: (job: AnalysisJob | null) => void;
  setCurrentResult: (result: AnalysisResult | null) => void;
  setUploading: (uploading: boolean) => void;
  setUploadProgress: (progress: number) => void;
  reset: () => void;
}

export const useAnalyzerStore = create<AnalyzerStore>()((set) => ({
  currentJob: null,
  currentResult: null,
  isUploading: false,
  uploadProgress: 0,
  setCurrentJob: (job) => set({ currentJob: job }),
  setCurrentResult: (result) => set({ currentResult: result }),
  setUploading: (uploading) => set({ isUploading: uploading }),
  setUploadProgress: (progress) => set({ uploadProgress: progress }),
  reset: () =>
    set({
      currentJob: null,
      currentResult: null,
      isUploading: false,
      uploadProgress: 0,
    }),
}));
