import { NextResponse } from "next/server";
import { ZodError } from "zod";
import { closePositionRequestSchema } from "../../../../src/lib/contracts";
import { closePosition } from "../../../../src/lib/engine-bridge";

export async function POST(request: Request) {
  try {
    const body = closePositionRequestSchema.parse(await request.json());

    const mt5Ticket = body.mt5_ticket ? Number(body.mt5_ticket) : body.position_id ? Number(body.position_id) : undefined;
    const payload = await closePosition({
      executionMode: body.execution_mode,
      mt5Ticket: isNaN(mt5Ticket!) ? undefined : mt5Ticket,
    });

    return NextResponse.json(payload);
  } catch (error) {
    if (error instanceof SyntaxError) {
      return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
    }
    if (error instanceof ZodError) {
      return NextResponse.json({ error: "Invalid close payload." }, { status: 400 });
    }
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json(
      { closed: false, message: `Close failed: ${message}` },
      { status: 500 },
    );
  }
}