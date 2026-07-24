import { NextResponse } from "next/server";
import { readPreparedCall, getConfiguredEngineRoot } from "../../../../src/lib/engine-bridge";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const symbol = (searchParams.get("symbol") ?? "R_100") as "R_75" | "R_100";

  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return NextResponse.json({
      available: false,
      reason: "Engine not configured",
      call: null,
    });
  }

  try {
    const call = await readPreparedCall(symbol);

    if (!call) {
      return NextResponse.json({
        available: false,
        reason: "No prepared call available",
        call: null,
      });
    }

    return NextResponse.json({
      available: true,
      call,
    });
  } catch {
    return NextResponse.json({
      available: false,
      reason: "Failed to read prepared call",
      call: null,
    });
  }
}