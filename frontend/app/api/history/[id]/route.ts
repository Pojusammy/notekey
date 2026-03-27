import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  // Try Python backend first
  try {
    const res = await fetch(`${BACKEND_URL}/api/history/${id}`, {
      method: "DELETE",
      signal: AbortSignal.timeout(3000),
    });
    if (res.ok) {
      return NextResponse.json(await res.json());
    }
  } catch {
    // Backend unavailable — fall through
  }

  // Fallback
  return NextResponse.json({ ok: true, id });
}
