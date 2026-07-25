import { NextResponse } from "next/server";
import { collectFreshTicks } from "../../../../src/lib/engine-bridge";

export async function POST() {
  try {
    const payload = await collectFreshTicks();
    return NextResponse.json(payload);
  } catch {
    return NextResponse.json(
      { collected: 0, errors: ["Unable to collect fresh ticks"], duration_ms: 0 },
      { status: 500 },
    );
  }
}
