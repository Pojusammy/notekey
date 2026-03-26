"use client";

import { useCallback, useRef, useState } from "react";
import { Navbar } from "@/components/layout/navbar";
import { useAnalyzerStore } from "@/stores/use-analyzer-store";
import { useKeyStore } from "@/stores/use-key-store";
import { api } from "@/utils/api";
import { cn } from "@/lib/utils";
import type { NoteEvent, NoteName } from "@/types/music";
import { NOTE_NAMES } from "@/types/music";

const FORMATS = ["MP3", "WAV", "M4A", "AAC", "MP4", "MOV", "WEBM"];

/** Format a raw digit string into M:SS or MM:SS */
function formatTimeInput(raw: string): string {
  // Strip everything except digits
  const digits = raw.replace(/\D/g, "").slice(0, 4);
  if (digits.length === 0) return "";
  if (digits.length <= 2) return digits;
  // Insert colon before last 2 digits
  const mins = digits.slice(0, digits.length - 2);
  const secs = digits.slice(digits.length - 2);
  return `${mins}:${secs}`;
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1048576).toFixed(1) + " MB";
}

export default function AnalyzerPage() {
  const {
    currentJob, currentResult, isUploading, uploadProgress,
    setCurrentJob, setCurrentResult, setUploading, setUploadProgress, reset,
  } = useAnalyzerStore();
  const selectedKey = useKeyStore((s) => s.selectedKey);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [processingStep, setProcessingStep] = useState("");
  const [processingProgress, setProcessingProgress] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [songKey, setSongKey] = useState<NoteName | "">("");
  const [startingNote, setStartingNote] = useState<NoteName | "">("");

  const loadFile = (file: File) => {
    setSelectedFile(file);
    setError(null);
  };

  const clearFile = () => {
    setSelectedFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleAnalyze = useCallback(async () => {
    if (!selectedFile) return;
    setError(null);

    try {
      // Show processing panel
      setCurrentJob({
        id: "temp", userId: "", jobType: "recording_analysis",
        inputFileUrl: "", selectedKey, status: "processing",
        createdAt: new Date().toISOString(),
      });

      // Simulate processing steps
      const steps = [
        "Extracting audio track…", "Normalizing audio…",
        "Running pitch detection…", "Segmenting melodic phrases…",
        "Mapping notes to tonic solfa…", "Finalizing results…",
      ];

      // Upload
      setUploading(true);
      setProcessingStep("Uploading file…");
      setProcessingProgress(0);
      const { fileUrl } = await api.uploadFile(selectedFile, setUploadProgress);
      setUploading(false);

      // Start analysis
      const { jobId } = await api.startAnalysis({
        fileUrl,
        selectedKey,
        ...(startTime && { startTime }),
        ...(endTime && { endTime }),
        ...(songKey && { songKey }),
        ...(startingNote && { startingNote }),
      });

      // Simulate step progression while polling
      let stepIdx = 0;
      const stepInterval = setInterval(() => {
        if (stepIdx < steps.length) {
          setProcessingStep(steps[stepIdx]);
          setProcessingProgress(((stepIdx + 1) / steps.length) * 100);
          stepIdx++;
        }
      }, 800);

      // Poll for completion
      const poll = async () => {
        const status = await api.getJobStatus(jobId);
        if (status.status === "completed") {
          clearInterval(stepInterval);
          setProcessingProgress(100);
          const result = await api.getResult(jobId);
          setCurrentResult({
            id: result.id, jobId,
            noteSequence: result.noteSequence as NoteEvent[],
            solfaSequence: result.solfaSequence,
            key: selectedKey,
            confidenceScore: result.confidenceScore,
            createdAt: new Date().toISOString(),
          });
          setCurrentJob(null);
        } else if (status.status === "failed") {
          clearInterval(stepInterval);
          setError(status.errorMessage || "Analysis failed");
          setCurrentJob(null);
        } else {
          setTimeout(poll, 2000);
        }
      };
      poll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setUploading(false);
      setCurrentJob(null);
    }
  }, [selectedFile, selectedKey, startTime, endTime, songKey, startingNote, setUploading, setUploadProgress, setCurrentJob, setCurrentResult]);

  const handleReset = () => {
    reset();
    setSelectedFile(null);
    setError(null);
    setProcessingStep("");
    setProcessingProgress(0);
    setStartTime("");
    setEndTime("");
    setSongKey("");
    setStartingNote("");
  };

  // Group notes into phrases (every 4-6 notes)
  const phrases = currentResult
    ? groupIntoPhrases(currentResult.noteSequence)
    : [];

  return (
    <>
      <Navbar />
      <div className="relative z-10 mx-auto max-w-[760px] px-6 pb-24 pt-14">
        {/* Header */}
        <div className="animate-fade-up mb-10">
          <h1 className="font-serif text-[clamp(28px,4vw,40px)] leading-[1.2] tracking-[-0.025em]">
            Analyze a recording
          </h1>
          <p className="mt-2 text-[14px] text-text-secondary">
            Upload an audio or short video clip and extract the melodic line as note names and tonic solfa.
          </p>
        </div>

        {/* ─── Upload state ─── */}
        {!currentJob && !currentResult && (
          <div className="animate-fade-up" style={{ animationDelay: "60ms" }}>
            {/* Upload zone */}
            <div
              ref={dropRef}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault(); setDragging(false);
                const f = e.dataTransfer.files[0];
                if (f) loadFile(f);
              }}
              onClick={() => fileInputRef.current?.click()}
              className={cn(
                "relative cursor-pointer rounded-[28px] border-2 border-dashed bg-surface px-8 py-14 text-center transition-all duration-200",
                dragging
                  ? "border-lime bg-lime-dim"
                  : "border-border-strong hover:border-lime hover:bg-lime-dim"
              )}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".mp3,.wav,.m4a,.aac,.mp4,.mov,.webm"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) loadFile(f);
                }}
              />
              <span className="block text-[40px]">🎧</span>
              <p className="mt-3.5 text-[16px] font-medium">
                Drop a file here or click to upload
              </p>
              <p className="mt-1.5 text-[13px] text-text-secondary">
                Audio or video up to 100MB · best results with clips under 60s
              </p>
              <div className="mt-4 flex flex-wrap justify-center gap-1.5">
                {FORMATS.map((f) => (
                  <span
                    key={f}
                    className="rounded-full border border-border-subtle bg-surface-3 px-2.5 py-0.5 font-mono text-[11px] tracking-[0.05em] text-text-muted"
                  >
                    {f}
                  </span>
                ))}
              </div>
            </div>

            {/* File preview */}
            {selectedFile && (
              <div className="mt-4 flex animate-fade-in items-center gap-4 rounded-[20px] border border-border-strong bg-surface px-6 py-5">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-lime/20 bg-lime-dim text-[20px]">
                  {selectedFile.type.startsWith("video") ? "🎬" : "🎵"}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] font-medium">{selectedFile.name}</p>
                  <p className="text-[12px] text-text-secondary">{formatBytes(selectedFile.size)}</p>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); clearFile(); }}
                  className="flex h-8 w-8 items-center justify-center rounded-md text-[18px] text-text-muted transition-colors hover:bg-danger/10 hover:text-danger"
                >
                  ✕
                </button>
              </div>
            )}

            {/* Analysis options */}
            {selectedFile && (
              <div className="mt-4 animate-fade-in rounded-[20px] border border-border-subtle bg-surface px-6 py-5">
                <h3 className="text-[13px] font-medium uppercase tracking-[0.06em] text-text-muted">
                  Analysis options
                </h3>

                {/* Time range */}
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[11px] font-medium uppercase tracking-[0.06em] text-text-muted">
                      Start time
                    </label>
                    <input
                      type="text"
                      inputMode="numeric"
                      placeholder="0:00"
                      value={startTime}
                      onChange={(e) => setStartTime(formatTimeInput(e.target.value))}
                      className="rounded-lg border border-border-subtle bg-surface-2 px-3 py-2.5 font-mono text-[13px] text-text-primary placeholder:text-text-muted/50 transition-colors focus:border-lime focus:outline-none"
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[11px] font-medium uppercase tracking-[0.06em] text-text-muted">
                      End time
                    </label>
                    <input
                      type="text"
                      inputMode="numeric"
                      placeholder="0:30"
                      value={endTime}
                      onChange={(e) => setEndTime(formatTimeInput(e.target.value))}
                      className="rounded-lg border border-border-subtle bg-surface-2 px-3 py-2.5 font-mono text-[13px] text-text-primary placeholder:text-text-muted/50 transition-colors focus:border-lime focus:outline-none"
                    />
                  </div>
                </div>
                <p className="mt-1.5 text-[11px] text-text-muted">
                  Specify the section to analyze (MM:SS). Leave blank to analyze the full clip.
                </p>

                {/* Key & Starting note */}
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[11px] font-medium uppercase tracking-[0.06em] text-text-muted">
                      Key of song <span className="normal-case tracking-normal text-text-muted/60">(optional)</span>
                    </label>
                    <select
                      value={songKey}
                      onChange={(e) => setSongKey(e.target.value as NoteName | "")}
                      className="rounded-lg border border-border-subtle bg-surface-2 px-3 py-2.5 font-mono text-[13px] text-text-primary transition-colors focus:border-lime focus:outline-none appearance-none"
                    >
                      <option value="">Auto-detect</option>
                      {NOTE_NAMES.map((n) => (
                        <option key={n} value={n}>
                          {n} Major
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[11px] font-medium uppercase tracking-[0.06em] text-text-muted">
                      Starting note <span className="normal-case tracking-normal text-text-muted/60">(optional)</span>
                    </label>
                    <select
                      value={startingNote}
                      onChange={(e) => setStartingNote(e.target.value as NoteName | "")}
                      className="rounded-lg border border-border-subtle bg-surface-2 px-3 py-2.5 font-mono text-[13px] text-text-primary transition-colors focus:border-lime focus:outline-none appearance-none"
                    >
                      <option value="">Auto-detect</option>
                      {NOTE_NAMES.map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <p className="mt-1.5 text-[11px] text-text-muted">
                  Providing the key and starting note helps improve detection accuracy.
                </p>
              </div>
            )}

            {/* Analyze button */}
            <div className="mt-6">
              <button
                onClick={handleAnalyze}
                disabled={!selectedFile}
                className={cn(
                  "flex w-full items-center justify-center gap-2 rounded-xl px-7 py-3.5 text-[14px] font-semibold transition-all",
                  selectedFile
                    ? "bg-lime text-canvas hover:bg-[#d4f55c] hover:-translate-y-px"
                    : "cursor-not-allowed bg-surface-3 text-text-muted"
                )}
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M2 8a6 6 0 1 0 12 0A6 6 0 0 0 2 8zm6-4v4l2.5 2.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                Analyze melody
              </button>
            </div>

            {/* Error */}
            {error && (
              <div className="mt-4 animate-fade-in rounded-xl border border-danger/30 bg-danger/5 p-4 text-[13px] text-danger">
                {error}
              </div>
            )}
          </div>
        )}

        {/* ─── Processing state ─── */}
        {currentJob && !currentResult && (
          <div className="animate-fade-up mt-6 rounded-[28px] border border-border-subtle bg-surface p-10 text-center">
            <div className="mx-auto mb-4 h-11 w-11 rounded-full border-2 border-border-strong border-t-lime animate-spin-slow" />
            <p className="font-serif text-[20px]">Analyzing melody…</p>
            <p className="mt-1.5 text-[13px] text-text-secondary">{processingStep}</p>
            <div className="mt-6 h-[3px] overflow-hidden rounded-sm bg-surface-3">
              <div
                className="h-full rounded-sm bg-lime transition-[width] duration-400"
                style={{ width: `${processingProgress}%` }}
              />
            </div>
          </div>
        )}

        {/* ─── Results ─── */}
        {currentResult && (
          <div className="animate-fade-up mt-8">
            <div className="mb-5 flex items-center justify-between">
              <h2 className="font-serif text-[24px] tracking-[-0.02em]">
                Here&apos;s the detected solfa
              </h2>
              <span className="text-[12px] text-text-secondary">
                {phrases.length} phrases · {currentResult.noteSequence.length} notes · key: {currentResult.key} Major
              </span>
            </div>

            <div className="flex flex-col gap-3">
              {phrases.map((phrase, pi) => (
                <div
                  key={pi}
                  className="animate-fade-up rounded-[20px] border border-border-subtle bg-surface px-6 py-5 transition-colors hover:border-border-strong"
                  style={{ animationDelay: `${pi * 80}ms` }}
                >
                  {/* Phrase header */}
                  <div className="mb-3.5 flex items-center justify-between">
                    <span className="font-mono text-[11px] tracking-[0.05em] text-text-muted">
                      ⏱ {phrase[0].startTime.toFixed(1)}s — {(phrase[phrase.length - 1].startTime + phrase[phrase.length - 1].duration).toFixed(1)}s
                    </span>
                    <span className="flex items-center gap-1.5 text-[11px] text-success">
                      <span className="h-[5px] w-[5px] rounded-full bg-success" />
                      {Math.round(currentResult.confidenceScore * 100)}% confidence
                    </span>
                  </div>

                  {/* Note chips */}
                  <div className="mb-3 flex flex-wrap gap-2">
                    {phrase.map((n, ni) => {
                      const isTonic = n.solfa === "Do";
                      return (
                        <div
                          key={ni}
                          className={cn(
                            "flex min-w-[48px] flex-col items-center gap-[3px] rounded-lg border px-3 py-2 transition-all hover:-translate-y-0.5 hover:bg-surface-3",
                            isTonic
                              ? "border-lime/30 bg-lime-dim"
                              : "border-border-subtle bg-surface-2 hover:border-border-strong"
                          )}
                        >
                          <span className={cn("font-mono text-[15px] font-medium leading-none", isTonic ? "text-lime" : "text-text-primary")}>
                            {n.noteName}{n.octave}
                          </span>
                          <span className="text-[10px] font-semibold tracking-[0.04em] leading-none text-lime">
                            {n.solfa}
                          </span>
                        </div>
                      );
                    })}
                  </div>

                  {/* Solfa line */}
                  <div className="border-t border-border-subtle pt-3 font-mono text-[13px] tracking-[0.04em] text-text-secondary">
                    {phrase.map((n, i) => (
                      <span key={i}>
                        {i > 0 && " — "}
                        <span className="font-medium text-lime">{n.solfa}</span>
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {/* Reset button */}
            <div className="mt-8 flex justify-center">
              <button
                onClick={handleReset}
                className="rounded-xl border border-border-strong bg-transparent px-6 py-3 text-[13px] font-medium text-text-secondary transition-colors hover:text-text-primary"
              >
                Analyze another clip
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

/** Group a flat note sequence into phrases of 4–6 notes */
function groupIntoPhrases(notes: NoteEvent[]): NoteEvent[][] {
  const phrases: NoteEvent[][] = [];
  let chunk: NoteEvent[] = [];
  for (const n of notes) {
    chunk.push(n);
    if (chunk.length >= 4 + Math.floor(Math.random() * 3)) {
      phrases.push(chunk);
      chunk = [];
    }
  }
  if (chunk.length > 0) phrases.push(chunk);
  return phrases;
}
