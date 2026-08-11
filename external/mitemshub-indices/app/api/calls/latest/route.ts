import { NextResponse } from "next/server";
import { getLatestCall } from "../../../../src/lib/engine-bridge";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  // Default to R_75 (Blueberry Volatility 75) — the system-wide default symbol.
  // The frontend always passes ?symbol= explicitly, but direct hits must not
  // silently flip to R_100 (the "why does it go back to V100" complaint).
  const symbol = (searchParams.get("symbol") ?? "R_75") as "R_75" | "R_100";
  const tradingMode = "sniper";

  const payload = await getLatestCall(symbol, tradingMode);
  return NextResponse.json(payload);
}
