import { NextResponse } from "next/server";
import { getPipelineDiagnostics } from "../../../../src/lib/engine-bridge";

export async function GET() {
  try {
    const payload = getPipelineDiagnostics();
    return NextResponse.json(payload);
  } catch {
    return NextResponse.json(
      {
        lastGuardianReason: null,
        lastStderr: null,
        lastRetryCount: 0,
        lastError: null,
        lastUpdatedAt: null,
      },
      { status: 500 },
    );
  }
}
