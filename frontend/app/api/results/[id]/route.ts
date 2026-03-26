import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

// Access the shared in-memory result store (local fallback)
const store = globalThis as unknown as {
  __results?: Map<string, { id: string; noteSequence: unknown[]; solfaSequence: string[]; confidenceScore: number }>;
};

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  // Try Python backend first
  try {
    const res = await fetch(`${BACKEND_URL}/api/results/${id}`, {
      signal: AbortSignal.timeout(3000),
    });
    if (res.ok) {
      return NextResponse.json(await res.json());
    }
  } catch {
    // Backend unavailable — fall through to local store
  }

  // Local fallback
  const result = store.__results?.get(id);
  if (!result) {
    return NextResponse.json({ detail: "Result not found" }, { status: 404 });
  }

  return NextResponse.json(result);
}
