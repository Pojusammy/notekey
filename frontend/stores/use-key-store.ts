import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { NoteName } from "@/types/music";

interface KeyStore {
  selectedKey: NoteName;
  setKey: (key: NoteName) => void;
}

export const useKeyStore = create<KeyStore>()(
  persist(
    (set) => ({
      selectedKey: "C",
      setKey: (key) => set({ selectedKey: key }),
    }),
    { name: "notekey-selected-key" }
  )
);
