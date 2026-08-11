import { NextResponse } from "next/server";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { getConfiguredEngineRoot } from "../../../../src/lib/engine-bridge";

// ── Pure file read (no Python subprocess) ─────────────────────────
// Previously this route spawned a Python subprocess per poll (cold import
// ~3-8s + work), and the calibration-health panel polls it every 15s —
// part of the subprocess churn that saturated the box and starved the
// live snapshot read (the root cause of 30-80s reads and "Bridge
// Offline" timeouts).  The computation is just JSONL aggregation over
// data/forecast_verdicts.json + journals/live_calibration_outcomes.jsonl,
// so it lives entirely in TS now: each poll is a few-millisecond file
// read with zero CPU contention.  Mirrors
// synthetic_trader/scripts/calibration_health.py exactly.

const MIN_SAMPLES = 10; // matches stage3_gate.MIN_STAGE3_SAMPLES default
const GATE_HIT_RATE_FLOOR = 0.5; // matches stage3_gate.GATE_HIT_RATE_FLOOR default
const HORIZON_LABELS = ["4h", "6h"] as const;

type HorizonDetail = {
  verdict: string | null;
  windows: number | null;
  coverage_p50: number | null;
  coverage_p90: number | null;
};

type TriggerRate = {
  trigger_type: string;
  count: number;
  target_hit_rate: number;
  stop_hit_rate: number;
  neither_rate: number;
  enough_samples: boolean;
  suppressed: boolean;
};

type SymbolCalibrationHealth = {
  horizons: Record<string, HorizonDetail>;
  triggers: TriggerRate[];
  cache_fresh: boolean;
};

function readLastJsonlRecord(raw: string): Record<string, unknown> {
  const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    try {
      const parsed = JSON.parse(lines[i]);
      if (parsed && typeof parsed === "object") return parsed as Record<string, unknown>;
    } catch {
      // skip malformed line
    }
  }
  return {};
}

function readAllJsonl(raw: string): Array<Record<string, unknown>> {
  const out: Array<Record<string, unknown>> = [];
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed && typeof parsed === "object") out.push(parsed as Record<string, unknown>);
    } catch {
      // skip malformed line
    }
  }
  return out;
}

function horizonDetail(entry: unknown): HorizonDetail {
  if (entry && typeof entry === "object") {
    const e = entry as Record<string, unknown>;
    return {
      verdict: typeof e.verdict === "string" ? e.verdict : null,
      windows: typeof e.windows === "number" ? e.windows : null,
      coverage_p50: typeof e.coverage_p50 === "number" ? e.coverage_p50 : null,
      coverage_p90: typeof e.coverage_p90 === "number" ? e.coverage_p90 : null,
    };
  }
  if (typeof entry === "string") {
    return { verdict: entry, windows: null, coverage_p50: null, coverage_p90: null };
  }
  return { verdict: null, windows: null, coverage_p50: null, coverage_p90: null };
}

export async function GET() {
  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return NextResponse.json({}, { status: 503 });
  }

  // ── Verdict cache (data/forecast_verdicts.json, JSONL, last record) ──
  let cache: Record<string, unknown> = {};
  try {
    cache = readLastJsonlRecord(await readFile(join(engineRoot, "data", "forecast_verdicts.json"), "utf8"));
  } catch {
    // no verdict cache yet
  }

  // ── Scored outcomes journal (journals/live_calibration_outcomes.jsonl) ──
  // Only measured trade outcomes count as evidence: a scored row is real
  // only when the call carried entry/stop/target levels, and Deriv-API
  // fallback rows are on the wrong price scale (excluded — mirrors the
  // Python scorer's filter).
  const buckets = new Map<string, { symbol: string; triggerType: string; count: number; targetHits: number; stopHits: number; neither: number }>();
  try {
    const outcomes = readAllJsonl(await readFile(join(engineRoot, "journals", "live_calibration_outcomes.jsonl"), "utf8"));
    for (const outcome of outcomes) {
      if (
        outcome.entry == null ||
        outcome.execution_stop == null ||
        outcome.primary_target == null ||
        outcome.scoring_source === "deriv_fallback"
      ) {
        continue;
      }
      const symbol = String(outcome.symbol ?? "");
      const triggerType = outcome.trigger_type == null ? "" : String(outcome.trigger_type);
      const key = `${symbol}\u0000${triggerType}`;
      const bucket = buckets.get(key) ?? { symbol, triggerType, count: 0, targetHits: 0, stopHits: 0, neither: 0 };
      bucket.count += 1;
      if (outcome.outcome_label === "target_hit") bucket.targetHits += 1;
      else if (outcome.outcome_label === "stop_hit") bucket.stopHits += 1;
      else if (outcome.outcome_label === "neither_reached") bucket.neither += 1;
      buckets.set(key, bucket);
    }
  } catch {
    // no outcomes journal yet
  }

  const triggerRates = new Map<string, TriggerRate[]>();
  for (const bucket of buckets.values()) {
    const target = bucket.count > 0 ? Math.round((bucket.targetHits / bucket.count) * 10000) / 10000 : 0;
    const stop = bucket.count > 0 ? Math.round((bucket.stopHits / bucket.count) * 10000) / 10000 : 0;
    const neither = bucket.count > 0 ? Math.round((bucket.neither / bucket.count) * 10000) / 10000 : 0;
    const row: TriggerRate = {
      trigger_type: bucket.triggerType,
      count: bucket.count,
      target_hit_rate: target,
      stop_hit_rate: stop,
      neither_rate: neither,
      enough_samples: bucket.count >= MIN_SAMPLES,
      // Mirrors stage3_gate: enough samples AND below the floor means this
      // call type is (or would be) suppressed.  Same rounded value as the
      // row displays so the flag and the shown rate never disagree.
      suppressed: bucket.count >= MIN_SAMPLES && target < GATE_HIT_RATE_FLOOR,
    };
    const list = triggerRates.get(bucket.symbol) ?? [];
    list.push(row);
    triggerRates.set(bucket.symbol, list);
  }

  const result: Record<string, SymbolCalibrationHealth> = {};
  for (const symbol of ["R_75", "R_100"]) {
    const symbolCache = (cache[symbol] && typeof cache[symbol] === "object" ? cache[symbol] : {}) as Record<string, unknown>;
    const horizons: Record<string, HorizonDetail> = {};
    for (const label of HORIZON_LABELS) {
      horizons[label] = horizonDetail(symbolCache[label]);
    }
    const cacheFresh = HORIZON_LABELS.every(
      (label) => horizons[label].verdict != null && horizons[label].windows != null,
    );
    result[symbol] = {
      horizons,
      triggers: (triggerRates.get(symbol) ?? []).sort((a, b) => a.trigger_type.localeCompare(b.trigger_type)),
      cache_fresh: cacheFresh,
    };
  }

  return NextResponse.json(result);
}
