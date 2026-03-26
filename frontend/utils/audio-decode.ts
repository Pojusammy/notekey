/**
 * Server-side audio decoding utility.
 * Uses ffmpeg to convert any audio/video file to mono 22050Hz raw PCM Float32.
 * This runs in Next.js API routes (Node.js), NOT in the browser.
 */

import { execFile } from "child_process";
import { promisify } from "util";
import fs from "fs";
import path from "path";
import os from "os";

const execFileAsync = promisify(execFile);

const TARGET_SAMPLE_RATE = 22050;

interface DecodeOptions {
  /** Start time in seconds */
  startTime?: number;
  /** End time in seconds */
  endTime?: number;
}

/**
 * Decode an audio/video file to a mono Float32Array at 22050Hz.
 * Requires ffmpeg to be installed on the system.
 */
export async function decodeAudioToFloat32(
  filePath: string,
  options: DecodeOptions = {}
): Promise<{ samples: Float32Array; sampleRate: number; durationSecs: number }> {
  // Build ffmpeg args
  const args: string[] = [];

  // Input seeking (before -i for fast seek)
  if (options.startTime != null && options.startTime > 0) {
    args.push("-ss", String(options.startTime));
  }

  args.push("-i", filePath);

  // Duration limit
  if (options.endTime != null && options.startTime != null) {
    const duration = options.endTime - (options.startTime || 0);
    if (duration > 0) {
      args.push("-t", String(duration));
    }
  } else if (options.endTime != null) {
    args.push("-t", String(options.endTime));
  }

  // Output: mono, 22050Hz, 32-bit float little-endian PCM, pipe to stdout
  const outPath = path.join(
    os.tmpdir(),
    `notekey_pcm_${Date.now()}_${Math.random().toString(36).slice(2)}.raw`
  );

  args.push(
    "-vn",              // strip video
    "-ac", "1",         // mono
    "-ar", String(TARGET_SAMPLE_RATE),
    "-f", "f32le",      // 32-bit float LE raw PCM
    "-y",               // overwrite
    outPath
  );

  try {
    await execFileAsync("ffmpeg", args, { maxBuffer: 500 * 1024 * 1024 });

    const rawBuffer = fs.readFileSync(outPath);
    const samples = new Float32Array(
      rawBuffer.buffer,
      rawBuffer.byteOffset,
      rawBuffer.byteLength / 4
    );

    const durationSecs = samples.length / TARGET_SAMPLE_RATE;

    return { samples, sampleRate: TARGET_SAMPLE_RATE, durationSecs };
  } finally {
    // Clean up temp file
    try {
      fs.unlinkSync(outPath);
    } catch {}
  }
}

/**
 * Parse a time string like "1:30" or "90" into seconds.
 */
export function parseTimeString(time: string): number {
  if (!time || !time.trim()) return 0;
  const parts = time.trim().split(":").map(Number);
  if (parts.length === 2) {
    return parts[0] * 60 + parts[1];
  }
  return parts[0] || 0;
}
