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

type AnalysisMode = "standard" | "fast";
type SourceType = "vocal" | "instrument" | "mixed";
type RangeProfile = "general" | "male_vocal" | "female_vocal" | "instrument_lead";

const ANALYSIS_MODE_OPTIONS: { value: AnalysisMode; label: string; hint: string }[] = [
  { value: "standard", label: "Standard lead", hint: "Clean, stable melody" },
  { value: "fast", label: "Fast interlude", hint: "Runs, trills & syncopation" },
];

const SOURCE_LABELS: Record<SourceType, string> = {
  vocal: "Vocal",
  instrument: "Instrument",
  mixed: "Mixed",
};

const RANGE_LABELS: Record<RangeProfile, string> = {
  general: "General",
  male_vocal: "Male vocal",
  female_vocal: "Female vocal",
  instrument_lead: "Instrument lead",
};

/** Format a raw digit string into M:SS or MM:SS */
function formatTimeInput(raw: string): string {
  const digits = raw.replace(/\D/g, "").slice(0, 4);
  if (digits.length === 0) return "";
  if (digits.length <= 2) return digits;
  const mins = digits.slice(0, digits.length - 2);
  const secs = digits.slice(digits.length - 2);
  return `${mins}:${secs}`;
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1048576).toFixed(1) + " MB";
}

function confidenceLabel(score: number): { text: string; color: string; dot: string } {
  if (score >= 0.8) return { text: "High confidence", color: "text-success", dot: "bg-success" };
  if (score >= 0.6) return { text: "Medium confidence", color: "text-warning", dot: "bg-warning" };
  return { text: "Low confidence", color: "text-danger", dot: "bg-danger" };
}

function phraseConfidence(phrase: NoteEvent[], globalScore: number): number {
  // Weight by duration — longer notes are more reliable
  const totalDur = phrase.reduce((s, n) => s + n.duration, 0);
  if (totalDur === 0) return globalScore;
  // Longer phrases with sustained notes get a confidence boost
  const avgDur = totalDur / phrase.length;
  const durBonus = Math.min(0.1, avgDur * 0.15);
  return Math.min(0.99, globalScore + durBonus);
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
  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>("standard");
  const [sourceType, setSourceType] = useState<SourceType>("vocal");
  const [rangeProfile, setRangeProfile] = useState<RangeProfile>("general");
  const [expandedPhrases, setExpandedPhrases] = useState<Set<number>>(new Set());

  const loadFile = (file: File) => {
    setSelectedFile(file);
    setError(null);
  };

  const clearFile = () => {
    setSelectedFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const togglePhraseDetail = (idx: number) => {
    setExpandedPhrases((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const handleAnalyze = useCallback(async () => {
    if (!selectedFile) return;
    setError(null);

    try {
      setCurrentJob({
        id: "temp", userId: "", jobType: "recording_analysis",
        inputFileUrl: "", selectedKey, status: "processing",
        createdAt: new Date().toISOString(),
      });

      const steps = [
        "Uploading audio…",
        "Extracting audio track…",
        "Isolating lead melody…",
        "Running pitch detection…",
        "Smoothing melodic contour…",
        "Mapping to tonic solfa…",
        "Building phrase structure…",
      ];

      setUploading(true);
      setProcessingStep(steps[0]);
      setProcessingProgress(0);
      const { fileUrl } = await api.uploadFile(selectedFile, setUploadProgress);
      setUploading(false);

      const { jobId } = await api.startAnalysis({
        fileUrl,
        selectedKey,
        analysisMode,
        ...(startTime && { startTime }),
        ...(endTime && { endTime }),
        ...(songKey && { songKey }),
        ...(startingNote && { startingNote }),
      });

      let stepIdx = 1;
      const stepInterval = setInterval(() => {
        if (stepIdx < steps.length) {
          setProcessingStep(steps[stepIdx]);
          setProcessingProgress(((stepIdx + 1) / steps.length) * 100);
          stepIdx++;
        }
      }, 900);

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
  }, [selectedFile, selectedKey, analysisMode, startTime, endTime, songKey, startingNote, setUploading, setUploadProgress, setCurrentJob, setCurrentResult]);

  const handleReset = () => {
    reset();
    setSelectedFile(null);
    setError(null);
    setProcessingStep("");
    setProcessingProgress(0);
    setAnalysisMode("standard");
    setStartTime("");
    setEndTime("");
    setSongKey("");
    setStartingNote("");
    setExpandedPhrases(new Set());
  };

  const phrases = currentResult
    ? groupIntoPhrases(currentResult.noteSequence)
    : [];

  const isLowConfidence = currentResult && currentResult.confidenceScore < 0.6;
  const isFewNotes = currentResult && currentResult.noteSequence.length <= 2;

  return (
    <>
      <Navbar />
      <div className="relative z-10 mx-auto max-w-[760px] px-6 pb-24 pt-14">
        {/* Header */}
        <div className="animate-fade-up mb-10">
          <h1 className="font-serif text-[clamp(28px,4vw,40px)] leading-[1.2] tracking-[-0.025em]">
            Extract lead melody
          </h1>
          <p className="mt-2 text-[14px] text-text-secondary">
            Upload a recording and extract the main melodic line as note names and tonic solfa.
          </p>
        </div>

        {/* ─── Upload + options state ─── */}
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

            {/* ── Analysis options ── */}
            {selectedFile && (
              <div className="mt-4 animate-fade-in rounded-[20px] border border-border-subtle bg-surface px-6 py-5">
                <h3 className="text-[13px] font-medium uppercase tracking-[0.06em] text-text-muted">
                  Extraction settings
                </h3>

                {/* Analysis mode toggle */}
                <div className="mt-4">
                  <label className="text-[11px] font-medium uppercase tracking-[0.06em] text-text-muted">
                    Analysis mode
                  </label>
                  <div className="mt-1.5 grid grid-cols-2 gap-2">
                    {ANALYSIS_MODE_OPTIONS.map((opt) => (
                      <button
                        key={opt.value}
                        onClick={() => setAnalysisMode(opt.value)}
                        className={cn(
                          "flex flex-col items-start gap-0.5 rounded-lg border px-3 py-2.5 text-left transition-all",
                          analysisMode === opt.value
                            ? "border-lime/30 bg-lime-dim"
                            : "border-border-subtle bg-surface-2 hover:border-border-strong"
                        )}
                      >
                        <span className={cn(
                          "flex items-center gap-2 font-mono text-[13px] font-medium",
                          analysisMode === opt.value ? "text-lime" : "text-text-primary"
                        )}>
                          <span className={cn(
                            "h-[6px] w-[6px] rounded-full",
                            analysisMode === opt.value ? "bg-lime" : "bg-text-muted/40"
                          )} />
                          {opt.label}
                        </span>
                        <span className="pl-[14px] text-[10px] text-text-muted">
                          {opt.hint}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Source type */}
                <div className="mt-3 flex flex-col gap-1.5">
                  <label className="text-[11px] font-medium uppercase tracking-[0.06em] text-text-muted">
                    Source type
                  </label>
                  <select
                    value={sourceType}
                    onChange={(e) => setSourceType(e.target.value as SourceType)}
                    className="rounded-lg border border-border-subtle bg-surface-2 px-3 py-2.5 font-mono text-[13px] text-text-primary transition-colors focus:border-lime focus:outline-none appearance-none"
                  >
                    {Object.entries(SOURCE_LABELS).map(([val, label]) => (
                      <option key={val} value={val}>{label}</option>
                    ))}
                  </select>
                </div>

                {/* Range profile */}
                <div className="mt-3">
                  <label className="text-[11px] font-medium uppercase tracking-[0.06em] text-text-muted">
                    Range profile
                  </label>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {Object.entries(RANGE_LABELS).map(([val, label]) => (
                      <button
                        key={val}
                        onClick={() => setRangeProfile(val as RangeProfile)}
                        className={cn(
                          "rounded-full border px-3 py-1.5 font-mono text-[11px] tracking-[0.03em] transition-all",
                          rangeProfile === val
                            ? "border-lime/30 bg-lime-dim text-lime"
                            : "border-border-subtle bg-surface-2 text-text-secondary hover:border-border-strong hover:text-text-primary"
                        )}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Divider */}
                <div className="my-4 border-t border-border-subtle" />

                {/* Clip range */}
                <h4 className="text-[11px] font-medium uppercase tracking-[0.06em] text-text-muted">
                  Clip range
                </h4>
                <div className="mt-2 grid grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[10px] tracking-[0.04em] text-text-muted">
                      Start
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
                    <label className="text-[10px] tracking-[0.04em] text-text-muted">
                      End
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
                  Trim to the exact phrase or interlude you want. Leave blank for the full clip.
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
                        <option key={n} value={n}>{n} Major</option>
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
                        <option key={n} value={n}>{n}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <p className="mt-1.5 text-[11px] text-text-muted">
                  Providing the key and starting note improves solfa accuracy.
                </p>
              </div>
            )}

            {/* Analyze button */}
            <div className="mt-6">
              <button
                onClick={handleAnalyze}
                disabled={!selectedFile}
                className={cn(
                  "flex w-full items-center justify-center gap-2.5 rounded-xl px-7 py-3.5 text-[14px] font-semibold transition-all",
                  selectedFile
                    ? "bg-lime text-canvas hover:bg-[#d4f55c] hover:-translate-y-px"
                    : "cursor-not-allowed bg-surface-3 text-text-muted"
                )}
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M8 2v12M5 5l3-3 3 3M3 10c0 2.2 2.2 4 5 4s5-1.8 5-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                Extract lead melody
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
            <p className="font-serif text-[20px]">Extracting lead melody…</p>
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
            {/* Results header */}
            <div className="mb-5 flex items-center justify-between">
              <h2 className="font-serif text-[24px] tracking-[-0.02em]">
                Lead melody
              </h2>
              <span className="text-[12px] text-text-secondary">
                {phrases.length} {phrases.length === 1 ? "phrase" : "phrases"} · {currentResult.noteSequence.length} notes · key: {currentResult.key} Major
              </span>
            </div>

            {/* Guidance messages for noisy/poor results */}
            {(isLowConfidence || isFewNotes) && (
              <div className="mb-4 animate-fade-in rounded-[16px] border border-warning/20 bg-warning/5 px-5 py-4">
                <p className="text-[13px] font-medium text-warning">
                  {isLowConfidence ? "Detection confidence is low" : "Very few notes detected"}
                </p>
                <ul className="mt-2 space-y-1 text-[12px] text-text-secondary">
                  <li>Try trimming to a shorter, cleaner section of the recording</li>
                  <li>Select &ldquo;Vocal&rdquo; or &ldquo;Instrument&rdquo; source type for better isolation</li>
                  <li>Choose a range profile that matches the singer or instrument</li>
                  {!songKey && <li>Setting the song key can improve solfa accuracy</li>}
                </ul>
              </div>
            )}

            {/* ── Phrase cards ── */}
            <div className="flex flex-col gap-3">
              {phrases.map((phrase, pi) => {
                const pConf = phraseConfidence(phrase, currentResult.confidenceScore);
                const conf = confidenceLabel(pConf);
                const isExpanded = expandedPhrases.has(pi);
                const phraseStart = phrase[0].startTime;
                const phraseEnd = phrase[phrase.length - 1].startTime + phrase[phrase.length - 1].duration;

                return (
                  <div
                    key={pi}
                    className="animate-fade-up rounded-[20px] border border-border-subtle bg-surface transition-colors hover:border-border-strong"
                    style={{ animationDelay: `${pi * 80}ms` }}
                  >
                    {/* Phrase header */}
                    <div className="flex items-center justify-between px-6 pt-5 pb-2">
                      <div className="flex items-center gap-3">
                        <span className="text-[13px] font-semibold text-text-primary">
                          Phrase {pi + 1}
                        </span>
                        <span className="font-mono text-[11px] tracking-[0.04em] text-text-muted">
                          {phraseStart.toFixed(1)}s — {phraseEnd.toFixed(1)}s
                        </span>
                      </div>
                      <span className={cn("flex items-center gap-1.5 text-[11px]", conf.color)}>
                        <span className={cn("h-[5px] w-[5px] rounded-full", conf.dot)} />
                        {conf.text}
                      </span>
                    </div>

                    {/* Primary: solfa line (the melody) */}
                    <div className="px-6 py-3">
                      <div className="font-mono text-[16px] leading-relaxed tracking-[0.02em]">
                        {phrase.map((n, i) => (
                          <span key={i}>
                            {i > 0 && <span className="mx-1 text-text-muted/40">—</span>}
                            <span className={cn(
                              "font-semibold",
                              n.solfa === "Do" ? "text-lime" : "text-text-primary"
                            )}>
                              {n.solfa}
                            </span>
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* Secondary: note names in smaller text */}
                    <div className="border-t border-border-subtle px-6 py-2.5">
                      <div className="font-mono text-[12px] tracking-[0.03em] text-text-secondary">
                        {phrase.map((n, i) => (
                          <span key={i}>
                            {i > 0 && <span className="mx-1 text-text-muted/30">·</span>}
                            <span className={n.solfa === "Do" ? "text-lime/70" : ""}>
                              {n.noteName}{n.octave}
                            </span>
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* Expandable: detailed note events */}
                    <div className="border-t border-border-subtle">
                      <button
                        onClick={() => togglePhraseDetail(pi)}
                        className="flex w-full items-center justify-between px-6 py-2.5 text-[11px] text-text-muted transition-colors hover:text-text-secondary"
                      >
                        <span>{isExpanded ? "Hide" : "Show"} detailed notes</span>
                        <svg
                          width="12" height="12" viewBox="0 0 12 12" fill="none"
                          className={cn("transition-transform duration-200", isExpanded && "rotate-180")}
                        >
                          <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      </button>

                      {isExpanded && (
                        <div className="animate-fade-in border-t border-border-subtle px-6 py-4">
                          <div className="flex flex-wrap gap-2">
                            {phrase.map((n, ni) => {
                              const isTonic = n.solfa === "Do";
                              return (
                                <div
                                  key={ni}
                                  className={cn(
                                    "flex min-w-[56px] flex-col items-center gap-1 rounded-lg border px-3 py-2.5 transition-all",
                                    isTonic
                                      ? "border-lime/30 bg-lime-dim"
                                      : "border-border-subtle bg-surface-2"
                                  )}
                                >
                                  <span className={cn("font-mono text-[14px] font-medium leading-none", isTonic ? "text-lime" : "text-text-primary")}>
                                    {n.noteName}{n.octave}
                                  </span>
                                  <span className="text-[10px] font-semibold tracking-[0.04em] leading-none text-lime">
                                    {n.solfa}
                                  </span>
                                  <span className="mt-0.5 font-mono text-[9px] leading-none text-text-muted">
                                    {n.startTime.toFixed(2)}s · {n.duration.toFixed(2)}s
                                  </span>
                                  <span className="font-mono text-[9px] leading-none text-text-muted">
                                    {n.frequency.toFixed(0)} Hz
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Reset button */}
            <div className="mt-8 flex justify-center">
              <button
                onClick={handleReset}
                className="rounded-xl border border-border-strong bg-transparent px-6 py-3 text-[13px] font-medium text-text-secondary transition-colors hover:text-text-primary"
              >
                Extract another melody
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

/** Group a flat note sequence into phrases based on time gaps */
function groupIntoPhrases(notes: NoteEvent[]): NoteEvent[][] {
  if (notes.length === 0) return [];

  const sorted = [...notes].sort((a, b) => a.startTime - b.startTime);

  const GAP_THRESHOLD = 0.3;
  const MAX_PHRASE = 8;

  const phrases: NoteEvent[][] = [];
  let chunk: NoteEvent[] = [sorted[0]];

  for (let i = 1; i < sorted.length; i++) {
    const prev = sorted[i - 1];
    const curr = sorted[i];
    const gap = curr.startTime - (prev.startTime + prev.duration);

    if (gap >= GAP_THRESHOLD || chunk.length >= MAX_PHRASE) {
      phrases.push(chunk);
      chunk = [curr];
    } else {
      chunk.push(curr);
    }
  }
  if (chunk.length > 0) phrases.push(chunk);
  return phrases;
}
