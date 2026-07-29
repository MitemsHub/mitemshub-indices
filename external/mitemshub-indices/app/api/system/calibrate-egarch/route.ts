import { NextResponse } from "next/server";
import { calibrateEgarch } from "../../../../src/lib/engine-bridge";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const symbol = (body.symbol ?? "R_100") as string;
    const csvPath = (body.csv_path ?? undefined) as string | undefined;

    const result = await calibrateEgarch(symbol, csvPath);
    return NextResponse.json(result);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Unknown calibration error";
    return NextResponse.json(
      { success: false, error: message },
      { status: 200 },
    );
  }
}
