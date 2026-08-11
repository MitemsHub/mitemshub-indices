import { NextResponse } from "next/server";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { getConfiguredEngineRoot } from "../../../../src/lib/engine-bridge";

// ── Pure file read (no Python subprocess) ─────────────────────────
// Previously this route spawned a Python subprocess per poll (cold import
// ~3-8s + work), and the pipeline-diagnostics panel polls it every 10s —
// together with calibration-stats and the warmup that kept the box
// saturated and starved the live snapshot read (the root cause of 30-80s
// reads and "Bridge Offline" timeouts).  The computation is just JSON
// aggregation over data/model_state/*.json, so it lives entirely in TS
// now: each poll is a few-millisecond file read with zero CPU contention.
// Mirrors synthetic_trader/scripts/replay_buffer_stats.py exactly.

type ReplayBufferSymbolStats = {
  buffer_size: number;
  capacity: number;
  fill_pct: number;
  total_seen: number;
  mini_batch_size: number;
  replay_ratio: number;
  label_0_count: number;
  label_1_count: number;
  label_balance: number;
  model_updates: number;
  model_version: string;
} | null | { error: string };

function emptyBufferStats(model: Record<string, unknown> | undefined): Record<string, unknown> {
  const meta = (model?.metadata ?? {}) as Record<string, unknown>;
  return {
    buffer_size: 0,
    capacity: 10_000,
    fill_pct: 0.0,
    total_seen: 0,
    mini_batch_size: 16,
    replay_ratio: 0.2,
    label_0_count: 0,
    label_1_count: 0,
    label_balance: 0.5,
    model_updates: typeof model?.updates === "number" ? model.updates : 0,
    model_version: typeof meta.version === "string" ? meta.version : "0.1.0",
  };
}

export async function GET() {
  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return NextResponse.json(
      { r_75: { error: "Engine root not configured" }, r_100: { error: "Engine root not configured" } },
      { status: 503 },
    );
  }

  const stateDir = join(engineRoot, "data", "model_state");
  const stats: Record<string, ReplayBufferSymbolStats> = {};

  for (const symbol of ["r_75", "r_100"] as const) {
    const candidates = [
      join(stateDir, `${symbol.toUpperCase()}_sniper.json`),
      join(stateDir, `${symbol}_sniper.json`),
    ];
    let raw: string | null = null;
    for (const p of candidates) {
      try {
        raw = await readFile(p, "utf8");
        break;
      } catch {
        // try next candidate
      }
    }
    if (raw === null) {
      stats[symbol] = null;
      continue;
    }
    try {
      const data = JSON.parse(raw) as Record<string, unknown>;
      const modelSection = (data.model ?? {}) as Record<string, unknown>;
      const bufPayload = modelSection.replay_buffer as Record<string, unknown> | null | undefined;

      if (bufPayload == null) {
        stats[symbol] = emptyBufferStats(modelSection) as ReplayBufferSymbolStats;
        continue;
      }

      const entries = (Array.isArray(bufPayload.entries) ? bufPayload.entries : []) as Array<Record<string, unknown>>;
      const capacity = typeof bufPayload.capacity === "number" ? bufPayload.capacity : 10_000;
      const totalSeen = typeof bufPayload.seen === "number" ? bufPayload.seen : 0;
      const miniBatchSize = typeof bufPayload.mini_batch_size === "number" ? bufPayload.mini_batch_size : 16;
      const replayRatio = typeof bufPayload.replay_ratio === "number" ? bufPayload.replay_ratio : 0.2;
      const bufferSize = entries.length;
      const label0 = entries.filter((e) => (e.label ?? 0) === 0).length;
      const label1 = entries.filter((e) => (e.label ?? 0) === 1).length;
      const totalLabels = label0 + label1 || 1;
      const meta = (modelSection.metadata ?? {}) as Record<string, unknown>;

      stats[symbol] = {
        buffer_size: bufferSize,
        capacity,
        fill_pct: capacity > 0 ? Math.round((bufferSize / capacity) * 1000) / 10 : 0,
        total_seen: totalSeen,
        mini_batch_size: miniBatchSize,
        replay_ratio: replayRatio,
        label_0_count: label0,
        label_1_count: label1,
        label_balance: Math.round((label0 / totalLabels) * 1000) / 1000,
        model_updates: typeof modelSection.updates === "number" ? modelSection.updates : 0,
        model_version: typeof meta.version === "string" ? meta.version : "0.1.0",
      };
    } catch (e) {
      stats[symbol] = { error: e instanceof Error ? e.message : String(e) };
    }
  }

  return NextResponse.json(stats);
}
