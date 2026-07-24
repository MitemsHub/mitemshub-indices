import { NextResponse } from "next/server";
import { getEngineDiskStatus } from "../../../../src/lib/engine-bridge";

/**
 * Lightweight engine-status endpoint.
 *
 * Returns the Python engine version (read once and cached in-memory)
 * and the MT5 last error (read from the shared disk file written by
 * mt5_data.py).  No Python subprocess is spawned after the first call.
 */
export async function GET() {
  try {
    const payload = await getEngineDiskStatus();
    return NextResponse.json(payload);
  } catch {
    return NextResponse.json(
      { engine_version: null, mt5_last_error: null },
      { status: 200 },
    );
  }
}
