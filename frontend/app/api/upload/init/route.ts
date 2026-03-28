import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

/**
 * Proxy to the Python backend's /api/upload/init endpoint.
 * Returns a Supabase presigned upload URL so the browser can upload large files
 * directly to Supabase — bypassing Vercel's 4.5 MB serverless body-size limit.
 * The request body is tiny JSON (just a filename), so it never hits the limit.
 */
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    if (!body.filename) {
      return NextResponse.json({ detail: "filename is required" }, { status: 400 });
    }

    const res = await fetch(`${BACKEND_URL}/api/upload/init`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: body.filename }),
      signal: AbortSignal.timeout(10000),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Failed to create upload URL" }));
      return NextResponse.json(err, { status: res.status });
    }

    return NextResponse.json(await res.json());
  } catch (error) {
    console.error("[upload/init] error:", error);
    return NextResponse.json({ detail: "Failed to create upload URL" }, { status: 500 });
  }
}
