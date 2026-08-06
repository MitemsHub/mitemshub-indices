import { NextResponse } from "next/server";
import { getConfiguredEngineRoot } from "../../../../src/lib/engine-bridge";
import { runPythonScript } from "../../../../src/lib/python-runner";

export async function GET() {
  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return NextResponse.json({}, { status: 503 });
  }

  try {
    const pythonScript = `
import json, sys
sys.path.insert(0, "${engineRoot.replace(/\\/g, "\\\\")}/src")
from synthetic_trader.scripts.calibration_health import get_calibration_health
print(json.dumps(get_calibration_health("${engineRoot.replace(/\\/g, "\\\\")}")))
`;

    const { stdout } = await runPythonScript({
      engineRoot,
      pythonScript,
      timeout: 15_000,
      label: "calibrationHealth",
    });

    const data = JSON.parse(stdout.trim());
    return NextResponse.json(data);
  } catch (error) {
    console.error("[calibration-health] Failed:", error);
    return NextResponse.json({}, { status: 500 });
  }
}
