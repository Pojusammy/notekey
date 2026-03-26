import { create } from "zustand";
import type { SavedSession } from "@/types/music";

interface HistoryStore {
  sessions: SavedSession[];
  isLoading: boolean;
  setSessions: (sessions: SavedSession[]) => void;
  addSession: (session: SavedSession) => void;
  removeSession: (id: string) => void;
  setLoading: (loading: boolean) => void;
}

export const useHistoryStore = create<HistoryStore>()((set) => ({
  sessions: [],
  isLoading: false,
  setSessions: (sessions) => set({ sessions }),
  addSession: (session) =>
    set((state) => ({ sessions: [session, ...state.sessions] })),
  removeSession: (id) =>
    set((state) => ({
      sessions: state.sessions.filter((s) => s.id !== id),
    })),
  setLoading: (loading) => set({ isLoading: loading }),
}));
