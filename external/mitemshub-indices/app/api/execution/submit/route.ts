import { NextResponse } from "next/server";
import { ZodError } from "zod";
import { submitOrderRequestSchema } from "../../../../src/lib/contracts";
import { submitOrder } from "../../../../src/lib/engine-bridge";

export async function POST(request: Request) {
  try {
    const body = submitOrderRequestSchema.parse(await request.json());

    const payload = await submitOrder({
      symbol: body.symbol,
      direction: body.direction_bias,
      entry: body.entry,
      stopLoss: body.stop_loss,
      takeProfit: body.take_profit,
      executionStop: body.execution_stop,
      primaryTarget: body.primary_target,
      extendedTarget: body.extended_target,
      executionMode: body.execution_mode,
      mt5Volume: body.mt5_volume,
    });

    return NextResponse.json(payload);
  } catch (error) {
    if (error instanceof SyntaxError) {
      return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
    }
    if (error instanceof ZodError) {
      return NextResponse.json({ error: "Invalid submit payload." }, { status: 400 });
    }
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json(
      { accepted: false, position_id: null, entry_price: null, stop_loss: null, take_profit: null, message: `Execution failed: ${message}` },
      { status: 500 },
    );
  }
}