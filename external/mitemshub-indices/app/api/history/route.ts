import { NextResponse } from "next/server";
import { getRecentHistory } from "../../../src/lib/engine-bridge";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const symbol = (searchParams.get("symbol") ?? "R_75") as "R_75" | "R_100";

  const payload = await getRecentHistory(symbol);
  return NextResponse.json(payload);
}
