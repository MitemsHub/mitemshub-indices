import { NextResponse } from "next/server";
import { readFile, writeFile, mkdir } from "fs/promises";
import { join, dirname } from "path";
import { getConfiguredEngineRoot } from "../../../../src/lib/engine-bridge";
import { runPythonScript } from "../../../../src/lib/python-runner";

// ── Cache ────────────────────────────────────────────────────────────
// get_horizon_forecast_stats re-runs the walk-forward coverage pass over
// the whole corpus (~50s solo, 60-120s+ under load: 2 symbols × 2 horizons
// × tens of thousands of ticks).  Two properties keep it from ever
// blocking a poll or starving the live snapshot:
//
//  1. The cache is PERSISTED TO DISK — in-memory-only caching meant every
//     module reload (e.g. a dev edit, which re-evaluates route modules)
//     cleared it and re-triggered a 60-120s subprocess on the next poll.
//     That repeated pass saturated the CPU and made live reads crawl.
//  2. REFRESH IS SINGLE-FLIGHT + STALE-WHILE-REVALIDATE — a poll never
//     waits for the pass.  If the cache is stale, the stored (possibly
//     older) data is returned immediately and the refresh runs in the
//     background; the next poll picks up the fresh result.
//
// The stats only change when the corpus grows, so a 15-minute TTL is more
// than enough and the panel stays fresh.
const FORECAST_TTL_MS = 15 * 60_000;
const FORECAST_SUBPROCESS_TIMEOUT_MS = 240_000;

interface CacheEntry {
  at: number;
  data: unknown;
}

function getCachePath(engineRoot: string): string {
  return join(engineRoot, "data", "forecast_horizon_cache.json");
}

async function readCache(engineRoot: string): Promise<CacheEntry | null> {
  try {
    const raw = await readFile(getCachePath(engineRoot), "utf8");
    const parsed = JSON.parse(raw) as CacheEntry;
    if (parsed && typeof parsed.at === "number" && parsed.data) {
      return parsed;
    }
  } catch {
    // Missing or corrupt cache — treat as empty.
  }
  return null;
}

async function writeCache(engineRoot: string, entry: CacheEntry): Promise<void> {
  try {
    const path = getCachePath(engineRoot);
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, JSON.stringify(entry), "utf8");
  } catch (error) {
    console.error("[forecast-horizon] cache write failed:", error);
  }
}

let refreshPromise: Promise<void> | null = null;

function startBackgroundRefresh(engineRoot: string): void {
  if (refreshPromise) return; // single-flight — never run two passes at once
  refreshPromise = (async () => {
    try {
      const data = await runForecastPass(engineRoot);
      await writeCache(engineRoot, { at: Date.now(), data });
    } catch (error) {
      console.error("[forecast-horizon] background refresh failed:", error);
    } finally {
      refreshPromise = null;
    }
  })();
}

async function runForecastPass(engineRoot: string): Promise<unknown> {
  const pythonScript = `
import json, sys
sys.path.insert(0, "${engineRoot.replace(/\\/g, "\\\\")}/src")
from synthetic_trader.scripts.horizon_forecast_stats import get_horizon_forecast_stats
print(json.dumps(get_horizon_forecast_stats("${engineRoot.replace(/\\/g, "\\\\")}")))
`;

  const { stdout } = await runPythonScript({
    engineRoot,
    pythonScript,
    timeout: FORECAST_SUBPROCESS_TIMEOUT_MS,
    label: "horizonForecast",
  });

  return JSON.parse(stdout.trim());
}

export async function GET() {
  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return NextResponse.json({}, { status: 503 });
  }

  const cached = await readCache(engineRoot);
  const fresh = cached && Date.now() - cached.at < FORECAST_TTL_MS;

  if (fresh) {
    // Cache is current — optionally refresh in the background near the
    // TTL boundary so the next cycle never blocks, but never block here.
    return NextResponse.json(cached!.data);
  }

  if (cached) {
    // Stale cache: serve the stored data immediately, refresh in background.
    startBackgroundRefresh(engineRoot);
    return NextResponse.json(cached.data);
  }

  if (refreshPromise) {
    // No cache yet and a pass is already running — tell the panel it is
    // computing rather than spawning a second 50-120s subprocess.
    return NextResponse.json({
      R_75: { error: "computing", horizons: {} },
      R_100: { error: "computing", horizons: {} },
    });
  }

  // Very first call: run the pass inline (blocking) — the panel shows a
  // fetch state meanwhile, and this only happens once per fresh checkout
  // or after the cache file is removed.
  try {
    const data = await runForecastPass(engineRoot);
    await writeCache(engineRoot, { at: Date.now(), data });
    return NextResponse.json(data);
  } catch (error) {
    console.error("[forecast-horizon] Failed:", error);
    return NextResponse.json(
      {
        R_75: { error: "forecast pass failed", horizons: {} },
        R_100: { error: "forecast pass failed", horizons: {} },
      },
      { status: 200 },
    );
  }
}
