import { NextResponse } from "next/server";
import { getSseStatus } from "../../../../src/lib/sse-state";

export async function GET() {
  try {
    const payload = getSseStatus();
    return NextResponse.json(payload);
  } catch {
    return NextResponse.json(
      {
        activeConnections: 0,
        maxConnections: 5,
        stateHistory: [],
        cacheStats: { hits: 0, misses: 0, hitRatio: 0 },
        uptime: 0,
        error: "Failed to read SSE status",
      },
      { status: 500 },
    );
  }
}
