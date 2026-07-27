import { NextResponse } from "next/server";
import { getConfiguredEngineRoot } from "../../../../src/lib/engine-bridge";
import { open, stat } from "node:fs/promises";
import { join } from "node:path";

type Tick = { epoch: number; price: number };

/**
 * Read the last N ticks from a CSV tick file.
 *
 * Uses a tail-read approach: reads the last ~256KB of the file, splits
 * into lines, and parses the most recent `limit` ticks. This avoids
 * reading the entire ~100K-line CSV on every 3-second poll.
 */
async function readLastTicks(
  csvPath: string,
  limit: number,
): Promise<Tick[]> {
  try {
    const s = await stat(csvPath);
    const fileSize = s.size;
    if (fileSize <= 0) return [];

    const handle = await open(csvPath, "r");
    try {
      // Read the last 256KB (enough for ~6000 lines at ~40 bytes/line)
      const readSize = Math.min(256 * 1024, fileSize);
      const buf = Buffer.allocUnsafe(readSize);
      const { bytesRead } = await handle.read(
        buf,
        0,
        readSize,
        fileSize - readSize,
      );
      const tail = buf.toString("utf8", 0, bytesRead);
      const lines = tail.split("\n").filter(Boolean);

      // Drop the first line if it's a partial line (not starting with a digit)
      const startIdx =
        lines.length > 0 && !lines[0].trim().match(/^\d/) ? 1 : 0;

      const ticks: Tick[] = [];
      for (let i = lines.length - 1; i >= startIdx && ticks.length < limit; i--) {
        const line = lines[i].trim();
        if (!line) continue;
        const parts = line.split(",");
        if (parts.length < 3) continue;
        try {
          const epoch = parseFloat(parts[0]);
          const price = parseFloat(parts[2]);
          if (Number.isFinite(epoch) && Number.isFinite(price)) {
            ticks.push({ epoch, price });
          }
        } catch {
          continue;
        }
      }
      ticks.reverse();
      return ticks;
    } finally {
      await handle.close();
    }
  } catch {
    return [];
  }
}

/**
 * GET /api/ticks — Returns recent tick data for R_75 and R_100.
 *
 * The PriceChart component polls this endpoint every 3 seconds to render
 * the live price line chart. Returns the last `limit` ticks per symbol
 * (default 100) sorted by epoch ascending.
 */
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const limit = Math.min(
    Math.max(parseInt(searchParams.get("limit") ?? "100", 10) || 100, 10),
    500,
  );

  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return NextResponse.json(
      { ticks: { R_75: [], R_100: [] }, timestamp: Date.now(), error: "Engine root not configured" },
      { status: 200 },
    );
  }

  const symbols = ["R_75", "R_100"] as const;
  const tickMap: Record<string, Tick[]> = {};

  for (const symbol of symbols) {
    const candidates = [
      join(engineRoot, "data", `${symbol}_ticks.csv`),
      join(engineRoot, "data", `${symbol.toLowerCase().replace("_", "")}_ticks.csv`),
      join(engineRoot, "data", `${symbol.toUpperCase()}_ticks.csv`),
    ];

    let ticks: Tick[] = [];
    for (const csvPath of candidates) {
      ticks = await readLastTicks(csvPath, limit);
      if (ticks.length > 0) break;
    }
    tickMap[symbol] = ticks;
  }

  return NextResponse.json({
    ticks: tickMap,
    timestamp: Date.now(),
  });
}
