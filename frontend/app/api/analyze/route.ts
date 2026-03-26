import { NextRequest, NextResponse } from "next/server";
import { randomUUID } from "crypto";
import fs from "fs";
import path from "path";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

// In-memory job store (fallback when Python backend is unavailable)
const store = globalThis as unknown as {
  __jobs?: Map<string, {
    status: string;
    selectedKey: string;
    fileUrl: string;
    startTime?: string;
    endTime?: string;
    songKey?: string;
    startingNote?: string;
    createdAt: string;
    completedAt?: string;
    errorMessage?: string;
  }>;
  __results?: Map<string, {
    id: string;
    noteSequence: unknown[];
    solfaSequence: string[];
    confidenceScore: number;
  }>;
};

if (!store.__jobs) store.__jobs = new Map();
if (!store.__results) store.__results = new Map();

export { store as jobStore };

// ── Helpers for JS fallback ──
const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"] as const;
const CHROMATIC_SOLFA = [
  "Do", "Di", "Re", "Ri", "Mi", "Fa",
  "Fi", "Sol", "Si", "La", "Li", "Ti",
] as const;

function midiToNoteName(midi: number) {
  return { noteName: NOTE_NAMES[((midi % 12) + 12) % 12], octave: Math.floor(midi / 12) - 1 };
}
function midiToFrequency(midi: number) {
  return 440 * Math.pow(2, (midi - 69) / 12);
}
function noteToSolfa(noteName: string, key: string) {
  const ni = NOTE_NAMES.indexOf(noteName as typeof NOTE_NAMES[number]);
  const ki = NOTE_NAMES.indexOf(key as typeof NOTE_NAMES[number]);
  if (ni === -1 || ki === -1) return "Do";
  return CHROMATIC_SOLFA[((ni - ki) % 12 + 12) % 12];
}
function parseTimeString(time: string): number {
  if (!time?.trim()) return 0;
  const parts = time.trim().split(":").map(Number);
  return parts.length === 2 ? parts[0] * 60 + parts[1] : parts[0] || 0;
}

// ── Try Python backend first, fall back to JS Basic Pitch ──

async function tryPythonBackend(body: Record<string, unknown>): Promise<{ jobId: string } | null> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(3000),
    });
    if (res.ok) {
      const data = await res.json();
      console.log("[analyze] Proxied to Python backend, jobId:", data.jobId);
      return data;
    }
  } catch {
    // Backend not available — fall through to JS
  }
  return null;
}

async function runLocalAnalysis(jobId: string) {
  const job = store.__jobs!.get(jobId);
  if (!job) return;

  try {
    const { decodeAudioToFloat32 } = await import("@/utils/audio-decode");
    const tf = await import("@tensorflow/tfjs");
    const { BasicPitch, outputToNotesPoly, noteFramesToTime, addPitchBendsToNoteEvents } =
      await import("@spotify/basic-pitch");

    const decodeOpts: { startTime?: number; endTime?: number } = {};
    if (job.startTime) decodeOpts.startTime = parseTimeString(job.startTime);
    if (job.endTime) decodeOpts.endTime = parseTimeString(job.endTime);

    console.log(`[analyze:local] Decoding audio: ${job.fileUrl}`, decodeOpts);
    const { samples, durationSecs } = await decodeAudioToFloat32(job.fileUrl, decodeOpts);
    console.log(`[analyze:local] Decoded ${samples.length} samples (${durationSecs.toFixed(1)}s)`);

    // Load model from disk
    const modelDir = path.resolve(process.cwd(), "node_modules/@spotify/basic-pitch/model");
    const modelJson = JSON.parse(fs.readFileSync(path.join(modelDir, "model.json"), "utf-8"));
    const weightData = fs.readFileSync(path.join(modelDir, "group1-shard1of1.bin"));
    const weightBuffer = weightData.buffer.slice(weightData.byteOffset, weightData.byteOffset + weightData.byteLength);

    const model = tf.loadGraphModel(tf.io.fromMemory({
      modelTopology: modelJson.modelTopology,
      weightSpecs: modelJson.weightsManifest[0].weights,
      weightData: weightBuffer,
      format: modelJson.format,
      generatedBy: modelJson.generatedBy,
      convertedBy: modelJson.convertedBy,
    }));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const basicPitch = new BasicPitch(model as any);

    const frames: number[][] = [];
    const onsets: number[][] = [];
    const contours: number[][] = [];

    console.log("[analyze:local] Running inference...");
    await basicPitch.evaluateModel(
      samples,
      (f: number[][], o: number[][], c: number[][]) => { frames.push(...f); onsets.push(...o); contours.push(...c); },
      (pct: number) => { if (Math.round(pct * 100) % 25 === 0) console.log(`[analyze:local] ${Math.round(pct * 100)}%`); }
    );

    const noteEvents = outputToNotesPoly(frames, onsets, 0.5, 0.3, 11, true, null, null, true, 11);
    const noteEventsInTime = noteFramesToTime(addPitchBendsToNoteEvents(contours, noteEvents));

    const effectiveKey = job.songKey || job.selectedKey || "C";
    const noteSequence = noteEventsInTime
      .sort((a, b) => a.startTimeSeconds - b.startTimeSeconds)
      .map((ev) => {
        const midi = Math.round(ev.pitchMidi);
        const { noteName, octave } = midiToNoteName(midi);
        return {
          noteName, octave,
          startTime: +ev.startTimeSeconds.toFixed(3),
          duration: +ev.durationSeconds.toFixed(3),
          frequency: +midiToFrequency(midi).toFixed(2),
          solfa: noteToSolfa(noteName, effectiveKey),
        };
      });

    const avgAmp = noteEventsInTime.length > 0
      ? noteEventsInTime.reduce((s, e) => s + e.amplitude, 0) / noteEventsInTime.length
      : 0;

    store.__results!.set(jobId, {
      id: randomUUID(),
      noteSequence,
      solfaSequence: noteSequence.map((n) => n.solfa),
      confidenceScore: +Math.min(0.99, Math.max(0.5, avgAmp * 1.2)).toFixed(3),
    });

    job.status = "completed";
    job.completedAt = new Date().toISOString();
    console.log(`[analyze:local] Job ${jobId} completed. ${noteSequence.length} notes.`);
  } catch (err) {
    console.error(`[analyze:local] Job ${jobId} failed:`, err);
    job.status = "failed";
    job.errorMessage = err instanceof Error ? err.message : "Analysis failed";
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { fileUrl, selectedKey = "C", startTime, endTime, songKey, startingNote } = body;

    if (!fileUrl) {
      return NextResponse.json({ detail: "fileUrl is required" }, { status: 400 });
    }

    // Try Python backend first (production path)
    const backendResult = await tryPythonBackend(body);
    if (backendResult) {
      // Backend accepted — polling will go through /api/jobs/[id] and /api/results/[id]
      // which also proxy to the backend
      return NextResponse.json(backendResult);
    }

    // Fallback: local JS analysis
    console.log("[analyze] Python backend unavailable, using local JS analysis");

    if (!fs.existsSync(fileUrl)) {
      return NextResponse.json({ detail: "Uploaded file not found" }, { status: 404 });
    }

    const jobId = randomUUID();
    store.__jobs!.set(jobId, {
      status: "processing",
      selectedKey,
      fileUrl,
      ...(startTime && { startTime }),
      ...(endTime && { endTime }),
      ...(songKey && { songKey }),
      ...(startingNote && { startingNote }),
      createdAt: new Date().toISOString(),
    });

    runLocalAnalysis(jobId).catch((err) => {
      console.error(`[analyze] Unhandled error for job ${jobId}:`, err);
      const job = store.__jobs!.get(jobId);
      if (job) { job.status = "failed"; job.errorMessage = "Unexpected analysis error"; }
    });

    return NextResponse.json({ jobId });
  } catch (error) {
    console.error("Analyze error:", error);
    return NextResponse.json({ detail: "Failed to start analysis" }, { status: 500 });
  }
}
