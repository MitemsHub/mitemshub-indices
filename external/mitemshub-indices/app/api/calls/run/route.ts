import { NextResponse } from "next/server";
import { ZodError } from "zod";
import { runCallRequestSchema } from "../../../../src/lib/contracts";
import {
  registerLiveSnapshot,
  unregisterLiveSnapshot,
  runFreshCall,
} from "../../../../src/lib/engine-bridge";

export async function POST(request: Request) {
  const controller = new AbortController();
  let symbol: string = "R_100";
  let tradingMode: "sniper" | "active_trader" | "volatility_harvest" = "sniper";

  try {
    const body = runCallRequestSchema.parse(await request.json());
    symbol = body.symbol;
    tradingMode = body.trading_mode ?? "sniper";

    // Register the controller so POST /api/calls/cancel can abort the Python process
    registerLiveSnapshot(symbol as "R_75" | "R_100", tradingMode, controller);

    const payload = await runFreshCall({
      symbol: symbol as "R_75" | "R_100",
      accountMode: body.account_mode,
      propAccountState: body.prop_account_state ?? null,
      propConnection: body.prop_connection ?? null,
      reusePreparedCall: "never",
      tradingMode,
      signal: controller.signal,
    });

    return NextResponse.json(payload);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return NextResponse.json(
        { status: "cancelled", message: "Live snapshot cancelled by user." },
        { status: 200 },
      );
    }

    if (error instanceof SyntaxError) {
      return NextResponse.json(
        { error: "Invalid JSON body." },
        { status: 400 },
      );
    }

    if (error instanceof ZodError) {
      return NextResponse.json(
        { error: "Invalid run-call payload." },
        { status: 400 },
      );
    }

    throw error;
  } finally {
    unregisterLiveSnapshot(symbol as "R_75" | "R_100", tradingMode);
  }
}
