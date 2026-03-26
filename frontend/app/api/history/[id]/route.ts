import { NextRequest, NextResponse } from "next/server";

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  // Placeholder — in production this deletes from the database
  return NextResponse.json({ ok: true, id });
}
