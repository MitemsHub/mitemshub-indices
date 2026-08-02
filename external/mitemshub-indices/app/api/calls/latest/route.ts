import { NextResponse } from "next/server";
import { getLatestCall } from "../../../../src/lib/engine-bridge";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const symbol = (searchParams.get("symbol") ?? "R_100") as "R_75" | "R_100";
  const tradingMode = "sniper";

  const payload = await getLatestCall(symbol, tradingMode);
  return NextResponse.json(payload);
}
