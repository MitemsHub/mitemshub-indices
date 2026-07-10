import { NextResponse } from "next/server";
import { getSystemStatus } from "../../../../src/lib/engine-bridge";

export async function GET() {
  const payload = await getSystemStatus();
  return NextResponse.json(payload);
}
