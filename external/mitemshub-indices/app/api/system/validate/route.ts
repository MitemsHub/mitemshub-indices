import { NextResponse } from "next/server";
import { validateEngineModules } from "../../../../src/lib/engine-bridge";

export async function GET() {
  try {
    const payload = await validateEngineModules();
    return NextResponse.json(payload);
  } catch {
    return NextResponse.json(
      { counted: 0, failed: 1, modules: [{ module: "synthetic_trader", status: "fail", error: "Validation route error" }], engine_root: null, python_version: null },
      { status: 500 },
    );
  }
}
