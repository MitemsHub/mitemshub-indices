import { NextResponse } from "next/server";
import { getConnectionStatus } from "../../../../src/lib/engine-bridge";

export async function GET(_request: Request) {
  const payload = await getConnectionStatus();
  return NextResponse.json(payload);
}
