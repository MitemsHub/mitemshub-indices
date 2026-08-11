import { NextResponse } from "next/server";
import { cancelLiveSnapshot } from "../../../../src/lib/engine-bridge";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      symbol?: string;
      trading_mode?: string;
    };

    const symbol = body.symbol === "R_75" || body.symbol === "R_100" ? body.symbol : "R_75";
    const tradingMode = "sniper";

    cancelLiveSnapshot(symbol, tradingMode);

    return NextResponse.json({ cancelled: true, symbol, trading_mode: tradingMode });
  } catch {
    return NextResponse.json({ cancelled: false }, { status: 400 });
  }
}
