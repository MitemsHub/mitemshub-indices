import { NextResponse } from "next/server";
import { readFile, readdir, writeFile, stat } from "node:fs/promises";
import { join } from "node:path";
import { getConfiguredEngineRoot } from "../../../../src/lib/engine-bridge";

// ── Pure file read (no Python subprocess) ─────────────────────────
// Previously this route spawned a Python subprocess per poll (cold import
// ~3-8s + work), and the pipeline-diagnostics panel polls it every 10s —
// together with replay-buffer-stats and the warmup that kept the box
// saturated and starved the live snapshot read.  The computation is just
// JSON aggregation over data/model_state/*.json, so it lives entirely in
// TS now: each poll is a few-millisecond file read with zero CPU
// contention.  Mirrors synthetic_trader/scripts/calibration_stats.py
// exactly (including the best-effort milestone persistence).

type CalibrationSymbolStats = {
  total_samples: number;
  positive_count: number;
  negative_count: number;
  avg_prediction: number;
  accuracy: number;
  model_updates: number;
  model_version: string;
  ready: boolean;
  progress_pct: number;
  milestones_reached: number[];
  milestone_30: boolean;
  milestone_100: boolean;
  milestone_500: boolean;
  loaded_from_disk: boolean;
  save_count: number;
  brier_score: number | null;
  last_save_epoch: number;
  last_save_age_seconds: number;
  file_size_bytes: number;
} | { error: string };

const MILESTONE_THRESHOLDS = [30, 100, 500];

export async function GET() {
  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return NextResponse.json({}, { status: 503 });
  }

  const stateDir = join(engineRoot, "data", "model_state");
  const result: Record<string, CalibrationSymbolStats> = {};

  let files: string[];
  try {
    files = await readdir(stateDir);
  } catch {
    return NextResponse.json(result);
  }

  for (const name of files.sort()) {
    if (name === ".gitkeep" || name.includes("_active_trader")) continue;
    const statePath = join(stateDir, name);
    try {
      const data = JSON.parse(await readFile(statePath, "utf8")) as Record<string, unknown>;
      const cal = (data.calibration ?? {}) as Record<string, unknown>;
      const predictions = (Array.isArray(cal.predictions) ? cal.predictions : []) as number[];
      const outcomes = (Array.isArray(cal.outcomes) ? cal.outcomes : []) as number[];
      const model = (data.model ?? {}) as Record<string, unknown>;
      const versioning = (data.versioning ?? {}) as Record<string, unknown>;

      const positiveCount = outcomes.filter((o) => o === 1).length;
      const negativeCount = outcomes.filter((o) => o === 0).length;
      const total = predictions.length;
      const avgPrediction = total > 0 ? predictions.reduce((a, b) => a + b, 0) / total : 0;
      const correct = predictions.reduce(
        (acc, p, i) => acc + ((p >= 0.5 && outcomes[i] === 1) || (p < 0.5 && outcomes[i] === 0) ? 1 : 0),
        0,
      );
      const accuracy = total > 0 ? correct / total : 0;

      const fileStat = await stat(statePath);

      // ── Milestone tracking ─────────────────────────────────
      // Mirrors the Python: persist newly-reached milestones back to the
      // state file (best-effort) so notifications don't re-fire on polls.
      const milestones = { ...((versioning.milestones ?? {}) as Record<string, unknown>) };
      const milestonesReached: number[] = [];
      let milestonesDirty = false;
      for (const threshold of MILESTONE_THRESHOLDS) {
        const key = `reached_${threshold}`;
        if (total >= threshold && !milestones[key]) {
          milestonesReached.push(threshold);
          milestones[key] = Date.now() / 1000;
          milestonesDirty = true;
        }
      }
      if (milestonesDirty) {
        try {
          (versioning as Record<string, unknown>).milestones = milestones;
          (data as Record<string, unknown>).versioning = versioning;
          await writeFile(statePath, JSON.stringify(data, null, 2), "utf8");
        } catch {
          // best-effort — don't crash the stats read for a write failure
        }
      }

      const meta = (model.metadata ?? {}) as Record<string, unknown>;
      const key = name.replace(/\.json$/, "");
      result[key] = {
        total_samples: total,
        positive_count: positiveCount,
        negative_count: negativeCount,
        avg_prediction: Math.round(avgPrediction * 10000) / 10000,
        accuracy: Math.round(accuracy * 10000) / 10000,
        model_updates: typeof model.updates === "number" ? model.updates : 0,
        model_version: typeof meta.version === "string" ? meta.version : "unknown",
        ready: total >= 30,
        progress_pct: Math.min(Math.round((total / 30) * 1000) / 10, 100.0),
        milestones_reached: milestonesReached,
        milestone_30: milestones.reached_30 != null,
        milestone_100: milestones.reached_100 != null,
        milestone_500: milestones.reached_500 != null,
        loaded_from_disk: total > 0 || (typeof model.updates === "number" && model.updates > 0),
        save_count: typeof versioning.save_count === "number" ? versioning.save_count : 0,
        brier_score: typeof versioning.brier_score === "number" ? versioning.brier_score : null,
        last_save_epoch: fileStat.mtimeMs / 1000,
        last_save_age_seconds: Math.round(Date.now() / 1000 - fileStat.mtimeMs / 1000),
        file_size_bytes: fileStat.size,
      };
    } catch (e) {
      result[name.replace(/\.json$/, "")] = { error: e instanceof Error ? e.message : String(e) };
    }
  }

  return NextResponse.json(result);
}
