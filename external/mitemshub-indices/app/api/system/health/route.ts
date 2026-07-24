import { NextResponse } from "next/server";
import { getHealthMetrics } from "../../../../src/lib/engine-bridge";

export async function GET() {
  try {
    const payload = await getHealthMetrics();
    return NextResponse.json(payload);
  } catch {
    return NextResponse.json(
      { error: "Unable to collect health metrics" },
      { status: 500 },
    );
  }
}
