import { NextRequest, NextResponse } from "next/server";
import { randomUUID } from "crypto";
import fs from "fs";
import path from "path";

// In-memory job store for development (replace with DB in production)
const jobs = globalThis as unknown as {
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

if (!jobs.__jobs) jobs.__jobs = new Map();
if (!jobs.__results) jobs.__results = new Map();

export { jobs as jobStore };

// ── Note name constants for MIDI → note mapping ──
const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"] as const;

const CHROMATIC_SOLFA = [
  "Do", "Di", "Re", "Ri", "Mi", "Fa",
  "Fi", "Sol", "Si", "La", "Li", "Ti",
] as const;

function midiToNoteName(midi: number): { noteName: string; octave: number } {
  const noteIdx = ((midi % 12) + 12) % 12;
  const octave = Math.floor(midi / 12) - 1;
  return { noteName: NOTE_NAMES[noteIdx], octave };
}

function midiToFrequency(midi: number): number {
  return 440 * Math.pow(2, (midi - 69) / 12);
}

function noteToSolfa(noteName: string, key: string): string {
  const noteIdx = NOTE_NAMES.indexOf(noteName as typeof NOTE_NAMES[number]);
  const keyIdx = NOTE_NAMES.indexOf(key as typeof NOTE_NAMES[number]);
  if (noteIdx === -1 || keyIdx === -1) return "Do";
  const interval = ((noteIdx - keyIdx) % 12 + 12) % 12;
  return CHROMATIC_SOLFA[interval];
}

function parseTimeString(time: string): number {
  if (!time || !time.trim()) return 0;
  const parts = time.trim().split(":").map(Number);
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return parts[0] || 0;
}

/**
 * Run Basic Pitch analysis on a file. This is async and sets
 * results in the in-memory store when done.
 */
async function runAnalysis(jobId: string) {
  const job = jobs.__jobs!.get(jobId);
  if (!job) return;

  try {
    // Dynamic imports to avoid bundling issues
    const { decodeAudioToFloat32 } = await import("@/utils/audio-decode");
    const tf = await import("@tensorflow/tfjs");
    const { BasicPitch, outputToNotesPoly, noteFramesToTime, addPitchBendsToNoteEvents } =
      await import("@spotify/basic-pitch");

    // 1. Decode audio to Float32Array at 22050Hz
    const decodeOpts: { startTime?: number; endTime?: number } = {};
    if (job.startTime) decodeOpts.startTime = parseTimeString(job.startTime);
    if (job.endTime) decodeOpts.endTime = parseTimeString(job.endTime);

    console.log(`[analyze] Decoding audio: ${job.fileUrl}`, decodeOpts);
    const { samples, durationSecs } = await decodeAudioToFloat32(job.fileUrl, decodeOpts);
    console.log(`[analyze] Decoded ${samples.length} samples (${durationSecs.toFixed(1)}s)`);

    // 2. Load Basic Pitch model from disk into memory
    //    (Node's fetch doesn't support file:// URLs, so we read manually)
    const modelDir = path.resolve(
      process.cwd(),
      "node_modules/@spotify/basic-pitch/model"
    );
    const modelJson = JSON.parse(fs.readFileSync(path.join(modelDir, "model.json"), "utf-8"));
    const weightData = fs.readFileSync(path.join(modelDir, "group1-shard1of1.bin"));
    const weightBuffer = weightData.buffer.slice(
      weightData.byteOffset,
      weightData.byteOffset + weightData.byteLength
    );

    const modelArtifacts = {
      modelTopology: modelJson.modelTopology,
      weightSpecs: modelJson.weightsManifest[0].weights,
      weightData: weightBuffer,
      format: modelJson.format,
      generatedBy: modelJson.generatedBy,
      convertedBy: modelJson.convertedBy,
    };

    console.log(`[analyze] Loading Basic Pitch model from memory...`);
    const model = tf.loadGraphModel(tf.io.fromMemory(modelArtifacts));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const basicPitch = new BasicPitch(model as any);

    // 3. Run inference
    const frames: number[][] = [];
    const onsets: number[][] = [];
    const contours: number[][] = [];

    console.log("[analyze] Running Basic Pitch inference...");
    await basicPitch.evaluateModel(
      samples,
      (f: number[][], o: number[][], c: number[][]) => {
        frames.push(...f);
        onsets.push(...o);
        contours.push(...c);
      },
      (percent: number) => {
        if (Math.round(percent * 100) % 25 === 0) {
          console.log(`[analyze] Progress: ${Math.round(percent * 100)}%`);
        }
      }
    );

    console.log(`[analyze] Inference complete. ${frames.length} frames.`);

    // 4. Post-process: extract note events
    const noteEvents = outputToNotesPoly(
      frames,
      onsets,
      0.5,   // onsetThreshold — higher = fewer false positives
      0.3,   // frameThreshold
      11,    // minNoteLen in frames (~127ms)
      true,  // inferOnsets
      null,  // maxFreq
      null,  // minFreq
      true,  // melodiaTrick — helps with monophonic melodies
      11,    // energyTolerance
    );

    const noteEventsWithBends = addPitchBendsToNoteEvents(contours, noteEvents);
    const noteEventsInTime = noteFramesToTime(noteEventsWithBends);

    console.log(`[analyze] Detected ${noteEventsInTime.length} note events.`);

    // 5. Determine the key to use for solfa mapping
    const effectiveKey = job.songKey || job.selectedKey || "C";

    // 6. Convert to our app's note format
    const noteSequence = noteEventsInTime
      .sort((a, b) => a.startTimeSeconds - b.startTimeSeconds)
      .map((event) => {
        const midi = Math.round(event.pitchMidi);
        const { noteName, octave } = midiToNoteName(midi);
        const frequency = midiToFrequency(midi);
        const solfa = noteToSolfa(noteName, effectiveKey);

        return {
          noteName,
          octave,
          startTime: +event.startTimeSeconds.toFixed(3),
          duration: +event.durationSeconds.toFixed(3),
          frequency: +frequency.toFixed(2),
          solfa,
        };
      });

    const solfaSequence = noteSequence.map((n) => n.solfa);

    // 7. Compute a confidence score from average amplitude
    const avgAmplitude =
      noteEventsInTime.length > 0
        ? noteEventsInTime.reduce((sum, e) => sum + e.amplitude, 0) / noteEventsInTime.length
        : 0;
    const confidenceScore = +Math.min(0.99, Math.max(0.5, avgAmplitude * 1.2)).toFixed(3);

    // 8. Store results
    jobs.__results!.set(jobId, {
      id: randomUUID(),
      noteSequence,
      solfaSequence,
      confidenceScore,
    });

    job.status = "completed";
    job.completedAt = new Date().toISOString();
    console.log(`[analyze] Job ${jobId} completed. ${noteSequence.length} notes detected.`);
  } catch (err) {
    console.error(`[analyze] Job ${jobId} failed:`, err);
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

    if (!fs.existsSync(fileUrl)) {
      return NextResponse.json({ detail: "Uploaded file not found" }, { status: 404 });
    }

    const jobId = randomUUID();

    jobs.__jobs!.set(jobId, {
      status: "processing",
      selectedKey,
      fileUrl,
      ...(startTime && { startTime }),
      ...(endTime && { endTime }),
      ...(songKey && { songKey }),
      ...(startingNote && { startingNote }),
      createdAt: new Date().toISOString(),
    });

    // Fire off analysis in the background (non-blocking)
    runAnalysis(jobId).catch((err) => {
      console.error(`[analyze] Unhandled error for job ${jobId}:`, err);
      const job = jobs.__jobs!.get(jobId);
      if (job) {
        job.status = "failed";
        job.errorMessage = "Unexpected analysis error";
      }
    });

    return NextResponse.json({ jobId });
  } catch (error) {
    console.error("Analyze error:", error);
    return NextResponse.json({ detail: "Failed to start analysis" }, { status: 500 });
  }
}
