import { NextRequest, NextResponse } from "next/server";

// Access the shared in-memory result store
const store = globalThis as unknown as {
  __results?: Map<string, { id: string; noteSequence: unknown[]; solfaSequence: string[]; confidenceScore: number }>;
};

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const result = store.__results?.get(id);
  if (!result) {
    return NextResponse.json({ detail: "Result not found" }, { status: 404 });
  }

  return NextResponse.json(result);
}
