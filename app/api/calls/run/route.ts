import { NextResponse } from "next/server";
import { runCallRequestSchema } from "../../../../src/lib/contracts";
import { runFreshCall } from "../../../../src/lib/engine-bridge";

export async function POST(request: Request) {
  const body = runCallRequestSchema.parse(await request.json());

  const payload = await runFreshCall({
    symbol: body.symbol,
    accountMode: body.account_mode,
    propAccountState: body.prop_account_state ?? null,
    propConnection: body.prop_connection ?? null,
  });

  return NextResponse.json(payload);
}
