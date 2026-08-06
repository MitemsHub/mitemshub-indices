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
from synthetic_trader.scripts.horizon_forecast_stats import get_horizon_forecast_stats
print(json.dumps(get_horizon_forecast_stats("${engineRoot.replace(/\\/g, "\\\\")}")))
`;

    const { stdout } = await runPythonScript({
      engineRoot,
      pythonScript,
      timeout: 60_000,  // 2 symbols × 2 horizons × ~40k ticks each needs headroom
      label: "horizonForecast",
    });

    const data = JSON.parse(stdout.trim());
    return NextResponse.json(data);
  } catch (error) {
    console.error("[forecast-horizon] Failed:", error);
    return NextResponse.json({}, { status: 500 });
  }
}
