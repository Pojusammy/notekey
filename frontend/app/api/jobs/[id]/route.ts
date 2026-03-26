import { NextRequest, NextResponse } from "next/server";

// Access the shared in-memory job store
const store = globalThis as unknown as {
  __jobs?: Map<string, { status: string; completedAt?: string; errorMessage?: string }>;
};

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

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
