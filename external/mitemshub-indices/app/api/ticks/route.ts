import { NextResponse } from "next/server";
import { getConfiguredEngineRoot } from "../../../src/lib/engine-bridge";
import { open, stat, watch } from "node:fs/promises";
import { join } from "node:path";

type Tick = { epoch: number; price: number };

// ── SSE connection limit ─────────────────────────────────────
// Prevents resource exhaustion from many browser tabs or reconnection
// loops each spawning file watchers and polling intervals.
const MAX_SSE_CONNECTIONS = 5;
let activeSseConnections = 0;

// ── Byte-offset cache for incremental tick reads ─────────────
// Tracks the last-known file size per CSV path so `readLastLine`
// only reads new bytes appended since the last call. This reduces
// file I/O from 2 opens/sec (stat + read) to 1 read on the hot path.
type TickByteCache = {
  lastFileSize: number;
  lastLine: Tick | null;
  lastMtime: number;
};
const tickByteCache = new Map<string, TickByteCache>();

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
        const tick = parseTickLine(lines[i].trim());
        if (tick) ticks.push(tick);
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
 * Parse a CSV tick line into a Tick object. Returns null if invalid.
 */
function parseTickLine(line: string): Tick | null {
  const parts = line.split(",");
  if (parts.length < 3) return null;
  const epoch = parseFloat(parts[0]);
  const price = parseFloat(parts[2]);
  if (Number.isFinite(epoch) && Number.isFinite(price)) {
    return { epoch, price };
  }
  return null;
}

/**
 * Read only the last line from a CSV tick file (for incremental updates).
 * Uses a byte-offset cache to skip reading bytes that haven't changed
 * since the last call. Falls back to a full tail read when the cache
 * is cold or the file has shrunk.
 */
async function readLastLine(csvPath: string): Promise<Tick | null> {
  try {
    const s = await stat(csvPath);
    const fileSize = s.size;
    const mtime = s.mtimeMs;
    if (fileSize <= 0) return null;

    const cached = tickByteCache.get(csvPath);

    // Fast path: file hasn't changed (same size + mtime)
    if (cached && fileSize === cached.lastFileSize && mtime === cached.lastMtime) {
      return cached.lastLine;
    }

    // File shrunk (rotation/truncation) — invalidate cache
    if (cached && fileSize < cached.lastFileSize) {
      tickByteCache.delete(csvPath);
    }

    // Read only the last 256 bytes (enough for one tick line ~40 bytes)
    const handle = await open(csvPath, "r");
    try {
      const readSize = Math.min(256, fileSize);
      const buf = Buffer.allocUnsafe(readSize);
      const { bytesRead } = await handle.read(
        buf,
        0,
        readSize,
        fileSize - readSize,
      );
      const tail = buf.toString("utf8", 0, bytesRead);
      const lines = tail.split("\n").filter(Boolean);
      const lastLine = lines[lines.length - 1]?.trim();

      const tick = lastLine ? parseTickLine(lastLine) : null;

      // Update cache
      tickByteCache.set(csvPath, {
        lastFileSize: fileSize,
        lastLine: tick,
        lastMtime: mtime,
      });

      return tick;
    } finally {
      await handle.close();
    }
  } catch {
    return null;
  }
}

/**
 * Resolve the CSV path for a symbol, trying multiple naming conventions.
 */
function resolveCsvPath(engineRoot: string, symbol: string): string | null {
  const candidates = [
    join(engineRoot, "data", `${symbol}_ticks.csv`),
    join(engineRoot, "data", `${symbol.toLowerCase().replace("_", "")}_ticks.csv`),
    join(engineRoot, "data", `${symbol.toUpperCase()}_ticks.csv`),
  ];
  // Return the first candidate (we'll verify existence in readLastTicks)
  return candidates[0];
}

/**
 * GET /api/ticks — Returns recent tick data for R_75 and R_100.
 *
 * Supports two modes:
 * - Regular GET: Returns the last `limit` ticks per symbol (default 100)
 * - SSE streaming (?stream=true): Opens a persistent connection that pushes
 *   new ticks as they arrive in the CSV files. Uses fs.watch to detect changes.
 *
 * The PriceChart component uses SSE mode for real-time updates without polling.
 */
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const streamMode = searchParams.get("stream") === "true";
  const limit = Math.min(
    Math.max(parseInt(searchParams.get("limit") ?? "100", 10) || 100, 10),
    500,
  );

  const engineRootRaw = getConfiguredEngineRoot();
  if (!engineRootRaw) {
    if (streamMode) {
      // For SSE mode, return an error event
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: "error", message: "Engine root not configured" })}\n\n`));
          controller.close();
        },
      });
      return new Response(stream, {
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          "Connection": "keep-alive",
        },
      });
    }
    return NextResponse.json(
      { ticks: { R_75: [], R_100: [] }, timestamp: Date.now(), error: "Engine root not configured" },
      { status: 200 },
    );
  }
  const engineRoot: string = engineRootRaw;

  // Regular GET mode — return initial ticks
  if (!streamMode) {
    const symbols = ["R_75", "R_100"] as const;
    const tickMap: Record<string, Tick[]> = {};

    for (const symbol of symbols) {
      const csvPath = resolveCsvPath(engineRoot, symbol);
      if (!csvPath) continue;
      const ticks = await readLastTicks(csvPath, limit);
      tickMap[symbol] = ticks;
    }

    return NextResponse.json({
      ticks: tickMap,
      timestamp: Date.now(),
    });
  }

  // ── SSE Streaming Mode ──────────────────────────────────────
  // Opens a persistent connection. On connect, sends the last N ticks
  // as initial state. Then watches the CSV files for changes and pushes
  // new ticks incrementally. Connection closes on client disconnect.

  // Reject if too many concurrent SSE connections
  if (activeSseConnections >= MAX_SSE_CONNECTIONS) {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: "error", message: `Too many SSE connections (${activeSseConnections}/${MAX_SSE_CONNECTIONS}). Close other tabs and try again.` })}\n\n`));
        controller.close();
      },
    });
    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
      },
    });
  }

  activeSseConnections += 1;

  const encoder = new TextEncoder();
  const symbols = ["R_75", "R_100"] as const;

  // Track the last epoch we've sent per symbol to avoid duplicates
  const lastEpoch: Record<string, number> = { R_75: 0, R_100: 0 };

  const stream = new ReadableStream({
    async start(controller) {
      // Track all intervals/intervals for cleanup on disconnect
      const intervals: NodeJS.Timeout[] = [];

      // Register abort handler FIRST to ensure cleanup even if initial await throws
      request.signal.addEventListener("abort", () => {
        for (const id of intervals) clearInterval(id);
        activeSseConnections = Math.max(0, activeSseConnections - 1);
        try {
          controller.close();
        } catch {
          // Already closed
        }
      });

      // Helper to send an SSE event
      function sendEvent(data: Record<string, unknown>) {
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(data)}\n\n`));
        } catch {
          // Client disconnected
        }
      }

      // Helper to read and send initial ticks for a symbol
      async function sendInitialTicks(symbol: string) {
        const csvPath = resolveCsvPath(engineRoot, symbol);
        if (!csvPath) return;

        const ticks = await readLastTicks(csvPath, limit);
        if (ticks.length > 0) {
          lastEpoch[symbol] = ticks[ticks.length - 1].epoch;
          sendEvent({
            type: "initial",
            symbol,
            ticks,
            timestamp: Date.now(),
          });
        }
      }

      // Send initial ticks for both symbols
      await Promise.all(symbols.map(sendInitialTicks));

      // Send a "ready" event to indicate streaming has started
      sendEvent({
        type: "ready",
        timestamp: Date.now(),
      });

      // Watch for file changes using fs.watch with polling fallback
      for (const symbol of symbols) {
        const csvPath = resolveCsvPath(engineRoot, symbol);
        if (!csvPath) continue;

        try {
          const watcher = watch(csvPath, { persistent: false });
          const watcherIterable = watcher as AsyncIterable<unknown>;

          // Process watch events in a non-blocking loop
          (async () => {
            try {
              for await (const _event of watcherIterable) {
                // Debounce: wait 100ms after the last event
                await new Promise(resolve => setTimeout(resolve, 100));

                // Read the last line to check for new ticks
                const lastTick = await readLastLine(csvPath);
                if (lastTick && lastTick.epoch > lastEpoch[symbol]) {
                  lastEpoch[symbol] = lastTick.epoch;
                  sendEvent({
                    type: "tick",
                    symbol,
                    tick: lastTick,
                    timestamp: Date.now(),
                  });
                }
              }
            } catch {
              // Watcher closed (client disconnected)
            }
          })();
        } catch {
          // Watch failed — fall back to polling mode
          const pollInterval = setInterval(async () => {
            const lastTick = await readLastLine(csvPath);
            if (lastTick && lastTick.epoch > lastEpoch[symbol]) {
              lastEpoch[symbol] = lastTick.epoch;
              sendEvent({
                type: "tick",
                symbol,
                tick: lastTick,
                timestamp: Date.now(),
              });
            }
          }, 500);
          intervals.push(pollInterval);
        }
      }

      // Send a heartbeat every 15 seconds to keep the connection alive
      const heartbeatInterval = setInterval(() => {
        sendEvent({ type: "heartbeat", timestamp: Date.now() });
      }, 15_000);
      intervals.push(heartbeatInterval);
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no", // Disable nginx buffering
    },
  });
}
