import { NextResponse } from "next/server";
import { testMt5Connection } from "../../../../src/lib/engine-bridge";

export async function POST() {
  try {
    const result = await testMt5Connection();
    return NextResponse.json(result);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Unknown error testing MT5 connection";
    return NextResponse.json({ success: false, error: message }, { status: 200 });
  }
}
