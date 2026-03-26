import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

// Access the shared in-memory job store (local fallback)
const store = globalThis as unknown as {
  __jobs?: Map<string, { status: string; completedAt?: string; errorMessage?: string }>;
};

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  // Try Python backend first
  try {
    const res = await fetch(`${BACKEND_URL}/api/jobs/${id}`, {
      signal: AbortSignal.timeout(3000),
    });
    if (res.ok) {
      return NextResponse.json(await res.json());
    }
  } catch {
    // Backend unavailable — fall through to local store
  }

  // Local fallback
  const job = store.__jobs?.get(id);
  if (!job) {
    return NextResponse.json({ detail: "Job not found" }, { status: 404 });
  }

  return NextResponse.json({
    id,
    status: job.status,
    completedAt: job.completedAt || null,
    errorMessage: job.errorMessage || null,
  });
}
