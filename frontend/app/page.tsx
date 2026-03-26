"use client";

import { useCallback, useRef } from "react";
import { Navbar } from "@/components/layout/navbar";
import { useDetectorStore } from "@/stores/use-detector-store";
import { useKeyStore } from "@/stores/use-key-store";
import { LivePitchDetector } from "@/utils/pitch-detector";
import { frequencyToNote, noteToSolfa } from "@/utils/solfa";
import type { NoteName } from "@/types/music";
import { cn } from "@/lib/utils";

export default function DetectorPage() {
  const { isListening, currentNote, setListening, setCurrentNote } =
    useDetectorStore();
  const selectedKey = useKeyStore((s) => s.selectedKey);
  const detectorRef = useRef<LivePitchDetector | null>(null);

  const toggle = useCallback(async () => {
    if (isListening) {
      detectorRef.current?.stop();
      detectorRef.current = null;
      setListening(false);
      return;
    }

    const detector = new LivePitchDetector();
    detectorRef.current = detector;

    try {
      await detector.start((result) => {
        if (result.frequency === 0 || result.clarity < 0.8) {
          setCurrentNote(null);
          return;
        }
        const { noteName, octave, centsOffset } = frequencyToNote(result.frequency);
        const solfa = noteToSolfa(noteName as NoteName, selectedKey);
        setCurrentNote({
          noteName: noteName as NoteName,
          octave,
          frequency: result.frequency,
          centsOffset,
          solfa,
          confidence: result.clarity,
        });
      });
      setListening(true);
    } catch {
      setListening(false);
    }
  }, [isListening, selectedKey, setListening, setCurrentNote]);

  // Cents bar position: -50..+50 mapped to 0..100%
  const centsPct = currentNote
    ? 50 + Math.max(-50, Math.min(50, currentNote.centsOffset))
    : 50;

  return (
    <>
      <Navbar />
      <div className="relative z-10 mx-auto max-w-[680px] px-6 pb-24 pt-16">
        {/* Header */}
        <div className="animate-fade-up text-center">
          <h1 className="font-serif text-[clamp(32px,5vw,46px)] leading-[1.15] tracking-[-0.025em]">
            Sing or play a note
          </h1>
          <p className="mx-auto mt-2.5 max-w-[380px] text-[15px] text-text-secondary">
            Hold any note and NoteKey will identify it and map it to tonic solfa in your chosen key.
          </p>
        </div>

        {/* Mic Stage */}
        <div className="mt-14 flex flex-col items-center gap-8">
          {/* Mic orbit */}
          <div className="relative h-[180px] w-[180px]">
            {/* Ripple rings — only visible when listening */}
            {isListening && (
              <div className="absolute -inset-[30px] pointer-events-none">
                <div className="animate-ripple-1 absolute inset-5 rounded-full border border-lime opacity-0" />
                <div className="animate-ripple-2 absolute inset-[5px] rounded-full border border-lime opacity-0" />
                <div className="animate-ripple-3 absolute -inset-3 rounded-full border border-lime opacity-0" />
              </div>
            )}

            {/* Mic button */}
            <button
              onClick={toggle}
              className={cn(
                "relative z-10 flex h-[180px] w-[180px] flex-col items-center justify-center gap-2.5 rounded-full border-2 transition-all duration-300",
                "shadow-[0_4px_16px_rgba(0,0,0,0.5),0_0_0_1px_rgba(255,255,255,0.05),inset_0_1px_0_rgba(255,255,255,0.06)]",
                "hover:scale-[1.04]",
                isListening
                  ? "border-lime bg-lime-dim shadow-[0_4px_16px_rgba(0,0,0,0.5),0_0_32px_rgba(200,240,74,0.18),inset_0_1px_0_rgba(255,255,255,0.06)]"
                  : "border-border-strong bg-surface hover:border-lime hover:shadow-[0_4px_16px_rgba(0,0,0,0.5),0_0_32px_rgba(200,240,74,0.18),inset_0_1px_0_rgba(255,255,255,0.06)]"
              )}
              style={{ transition: "all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)" }}
            >
              <span className={cn("text-[44px] leading-none transition-transform duration-300", isListening && "scale-110")}>
                🎙️
              </span>
              <span className={cn("text-[11px] font-medium uppercase tracking-[0.1em]", isListening ? "text-lime" : "text-text-muted")}>
                {isListening ? "Listening…" : "Tap to listen"}
              </span>
            </button>
          </div>

          {/* Status bar */}
          <div
            className={cn(
              "flex items-center gap-2 rounded-full border px-5 py-2.5 text-[12px] tracking-[0.04em]",
              isListening
                ? "border-lime/30 bg-lime-dim text-lime"
                : "border-border-subtle bg-surface-2 text-text-muted"
            )}
          >
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                isListening ? "bg-lime animate-blink" : "bg-text-muted"
              )}
            />
            {isListening
              ? "Listening — hold your note steady"
              : currentNote
                ? "Stopped — tap to listen again"
                : "Ready — choose a key and tap the mic"}
          </div>
        </div>

        {/* Result Card */}
        <div
          className={cn(
            "mt-12 grid grid-cols-2 gap-8 rounded-[28px] border bg-surface p-9 transition-all duration-300 max-sm:grid-cols-1 max-sm:gap-5",
            "shadow-[0_1px_3px_rgba(0,0,0,0.4),0_0_0_1px_rgba(255,255,255,0.04)]",
            currentNote
              ? "border-border-strong opacity-100 shadow-[0_4px_16px_rgba(0,0,0,0.5),0_0_0_1px_rgba(255,255,255,0.05)]"
              : "border-border-subtle opacity-40 blur-[1px]"
          )}
        >
          {/* Note */}
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] font-medium uppercase tracking-[0.1em] text-text-muted">
              Note
            </span>
            <span className="font-serif text-[68px] leading-none tracking-[-0.03em] max-sm:text-[56px]">
              {currentNote ? `${currentNote.noteName}${currentNote.octave}` : "—"}
            </span>
            <span className="font-mono text-[13px] text-text-secondary">
              {currentNote ? `${currentNote.frequency.toFixed(1)} Hz` : "—"}
            </span>
          </div>

          {/* Solfa */}
          <div className="flex flex-col gap-1.5">
            <span className="text-[11px] font-medium uppercase tracking-[0.1em] text-text-muted">
              Tonic Solfa
            </span>
            <span className="font-serif text-[68px] leading-none tracking-[-0.03em] text-lime max-sm:text-[56px]">
              {currentNote?.solfa ?? "—"}
            </span>
            <span className="font-mono text-[13px] text-text-secondary">
              {currentNote ? `Key of ${selectedKey}` : "—"}
            </span>
          </div>

          {/* Cents bar — spans full width */}
          <div className="col-span-full flex flex-col gap-2">
            <span className="text-[11px] font-medium uppercase tracking-[0.1em] text-text-muted">
              Tuning
            </span>
            <div className="relative h-1 rounded-sm bg-surface-3">
              {/* Center mark */}
              <div className="absolute left-1/2 top-[-4px] h-3 w-0.5 -translate-x-1/2 rounded-sm bg-border-strong" />
              {/* Cursor */}
              <div
                className="absolute top-[-5px] h-3.5 w-3.5 -translate-x-1/2 rounded-full bg-lime shadow-[0_0_8px_var(--color-lime-glow)] transition-[left] duration-100"
                style={{ left: `${centsPct}%` }}
              />
            </div>
            <div className="flex justify-between font-mono text-[10px] text-text-muted">
              <span>−50¢</span>
              <span>In tune</span>
              <span>+50¢</span>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
