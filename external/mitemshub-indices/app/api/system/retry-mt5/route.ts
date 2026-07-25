import { NextResponse } from "next/server";
import { retryMt5Connection } from "../../../../src/lib/engine-bridge";

export async function POST() {
  try {
    const result = await retryMt5Connection();
    return NextResponse.json(result);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Unknown error retrying MT5 connection";
    return NextResponse.json({ success: false, error: message }, { status: 200 });
  }
}
