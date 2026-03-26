"use client";

import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { NOTE_NAMES, type NoteName } from "@/types/music";
import { useKeyStore } from "@/stores/use-key-store";
import { cn } from "@/lib/utils";

const DISPLAY_KEYS = [
  "C", "C#/Db", "D", "D#/Eb", "E", "F",
  "F#/Gb", "G", "G#/Ab", "A", "A#/Bb", "B",
];

export function KeySelectorPill() {
  const { selectedKey, setKey } = useKeyStore();
  const [open, setOpen] = useState(false);
  const [tempKey, setTempKey] = useState(selectedKey);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const openModal = () => {
    setTempKey(selectedKey);
    setOpen(true);
  };

  const confirm = () => {
    setKey(tempKey);
    setOpen(false);
  };

  const modal = open ? (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}
    >
      <div className="animate-fade-up w-[420px] max-w-[calc(100vw-32px)] rounded-[28px] border border-border-strong bg-surface p-7 shadow-[0_4px_16px_rgba(0,0,0,0.5),0_0_0_1px_rgba(255,255,255,0.05)]">
        <h2 className="font-serif text-[22px] tracking-[-0.01em]">Choose a key</h2>
        <p className="mt-1.5 text-[13px] text-text-secondary">
          Tonic solfa will be mapped relative to this key.
        </p>

        <div className="mt-6 grid grid-cols-4 gap-2">
          {DISPLAY_KEYS.map((display) => {
            const noteKey = display.split("/")[0] as NoteName;
            return (
              <button
                key={display}
                onClick={() => setTempKey(noteKey)}
                className={cn(
                  "rounded-lg border bg-surface-2 px-1 py-2.5 font-mono text-[14px] transition-all",
                  tempKey === noteKey
                    ? "border-lime bg-lime-dim text-lime"
                    : "border-border-subtle text-text-secondary hover:border-border-strong hover:bg-surface-3 hover:text-text-primary"
                )}
              >
                {display}
              </button>
            );
          })}
        </div>

        <div className="mt-5 flex justify-end gap-2.5">
          <button
            onClick={() => setOpen(false)}
            className="rounded-lg border border-border-strong bg-transparent px-5 py-2.5 text-[13px] font-medium text-text-secondary transition-colors hover:text-text-primary"
          >
            Cancel
          </button>
          <button
            onClick={confirm}
            className="rounded-lg border-none bg-lime px-5 py-2.5 text-[13px] font-semibold text-canvas transition-colors hover:bg-[#d4f55c]"
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  ) : null;

  return (
    <>
      {/* Pill trigger */}
      <button
        onClick={openModal}
        className="flex items-center gap-2 rounded-full border border-border-subtle bg-surface px-3.5 py-1.5 transition-all hover:border-border-strong hover:bg-surface-2"
      >
        <span className="h-2 w-2 rounded-full bg-lime shadow-[0_0_8px_var(--color-lime-glow)]" />
        <span className="text-[12px] uppercase tracking-[0.04em] text-text-secondary">
          Key
        </span>
        <span className="font-mono text-[13px] font-medium text-text-primary">
          {selectedKey} Major
        </span>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M3 4.5L6 7.5L9 4.5" stroke="#9a9690" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>

      {/* Portal modal — rendered outside nav to avoid backdrop-filter stacking context */}
      {mounted && createPortal(modal, document.body)}
    </>
  );
}
