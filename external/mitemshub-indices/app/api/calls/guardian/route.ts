import { NextResponse } from "next/server";
import { getGuardianStatus } from "../../../../src/lib/engine-bridge";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const symbol = (searchParams.get("symbol") ?? "R_100") as "R_75" | "R_100";
  const tradingMode = (searchParams.get("trading_mode") ?? "sniper") as
    | "sniper"
    | "active_trader"
    | "volatility_harvest";

  const payload = await getGuardianStatus(symbol, tradingMode);
  return NextResponse.json(payload);
}
