import { NextRequest, NextResponse } from "next/server";
import { writeFile, mkdir } from "fs/promises";
import path from "path";
import { randomUUID } from "crypto";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const UPLOAD_DIR = path.join(process.cwd(), "uploads");

const ALLOWED_EXTENSIONS = new Set([
  ".mp3", ".wav", ".m4a", ".aac",
  ".mp4", ".mov", ".webm",
]);

const MAX_SIZE = 100 * 1024 * 1024; // 100MB

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData();
    const file = formData.get("file") as File | null;

    if (!file) {
      return NextResponse.json({ detail: "No file provided" }, { status: 400 });
    }

    if (file.size > MAX_SIZE) {
      return NextResponse.json({ detail: "File exceeds 100MB limit" }, { status: 400 });
    }

    const ext = path.extname(file.name).toLowerCase();
    if (!ALLOWED_EXTENSIONS.has(ext)) {
      return NextResponse.json(
        { detail: `Unsupported file type: ${ext}` },
        { status: 400 }
      );
    }

    // Try proxying to Python backend first
    try {
      const backendForm = new FormData();
      backendForm.append("file", file);
      const res = await fetch(`${BACKEND_URL}/api/upload`, {
        method: "POST",
        body: backendForm,
        signal: AbortSignal.timeout(30000),
      });
      if (res.ok) {
        const data = await res.json();
        console.log("[upload] Proxied to Python backend");
        return NextResponse.json(data);
      }
    } catch {
      // Backend unavailable — fall through to local storage
    }

    // Local fallback
    console.log("[upload] Python backend unavailable, saving locally");
    await mkdir(UPLOAD_DIR, { recursive: true });

    const fileId = randomUUID();
    const filename = `${fileId}${ext}`;
    const filePath = path.join(UPLOAD_DIR, filename);

    const buffer = Buffer.from(await file.arrayBuffer());
    await writeFile(filePath, buffer);

    return NextResponse.json({
      fileUrl: filePath,
      fileId,
      fileName: file.name,
      fileSize: file.size,
    });
  } catch (error) {
    console.error("Upload error:", error);
    return NextResponse.json(
      { detail: "Upload failed. Please try again." },
      { status: 500 }
    );
  }
}
