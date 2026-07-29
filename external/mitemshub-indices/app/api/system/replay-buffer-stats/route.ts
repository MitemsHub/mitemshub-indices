import { NextResponse } from "next/server";
import { getConfiguredEngineRoot } from "../../../../src/lib/engine-bridge";
import { runPythonScript } from "../../../../src/lib/python-runner";

export async function GET() {
  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return NextResponse.json(
      { r_75: { error: "Engine root not configured" }, r_100: { error: "Engine root not configured" } },
      { status: 503 },
    );
  }

  try {
    const pythonScript = `
import json, sys
sys.path.insert(0, "${engineRoot.replace(/\\/g, "\\\\")}/src")
from synthetic_trader.scripts.replay_buffer_stats import get_replay_buffer_stats
print(json.dumps(get_replay_buffer_stats("${engineRoot.replace(/\\/g, "\\\\")}")))
`;

    const { stdout } = await runPythonScript({
      engineRoot,
      pythonScript,
      timeout: 15_000,
      label: "replayBufferStats",
    });

    const data = JSON.parse(stdout.trim());
    return NextResponse.json(data);
  } catch (error) {
    console.error("[replay-buffer-stats] Failed:", error);
    return NextResponse.json(
      {
        r_75: { error: "Stats unavailable" },
        r_100: { error: "Stats unavailable" },
      },
      { status: 500 },
    );
  }
}
