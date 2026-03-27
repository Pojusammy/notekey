import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function GET() {
  // Try Python backend first
  try {
    const res = await fetch(`${BACKEND_URL}/api/history`, {
      signal: AbortSignal.timeout(3000),
    });
    if (res.ok) {
      return NextResponse.json(await res.json());
    }
  } catch {
    // Backend unavailable — fall through to empty
  }

  // Fallback: no saved sessions
  return NextResponse.json([]);
}
