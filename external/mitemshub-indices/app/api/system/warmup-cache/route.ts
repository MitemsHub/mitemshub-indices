import { NextResponse } from "next/server";
import { getWarmupCacheState } from "../../../../src/lib/engine-bridge";

/** GET /api/system/warmup-cache — raw warmup cache state for debugging.
 *
 * Returns the per-symbol hit/miss counters and the full CSV mtime timestamp
 * map, so you can inspect what the warmup cache knows without fetching the
 * entire health payload.
 *
 * Example response:
 * ```json
 * {
 *   "hits": { "R_75": 3, "R_100": 5 },
 *   "misses": { "R_75": 1, "R_100": 2 },
 *   "csvTimestamps": [
 *     { "key": "R_75_sniper", "csvMtime": 1712345678000, "cachedAt": 1712345680000, "ageMs": 12000 }
 *   ]
 * }
 * ``` */
export async function GET(): Promise<Response> {
  const state = getWarmupCacheState();
  return NextResponse.json(state);
}
