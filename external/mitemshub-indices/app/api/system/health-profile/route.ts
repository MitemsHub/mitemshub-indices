import { NextResponse } from "next/server";
import { stat, readFile, open } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join } from "node:path";

type Timing = { label: string; ms: number; bytes?: number };

const ENGINE_ROOT = process.env.SYNTHETIC_ENGINE_ROOT?.trim() ?? null;

export async function GET() {
  const timings: Timing[] = [];
  const failures: string[] = [];

  if (!ENGINE_ROOT) {
    return NextResponse.json({
      error: "SYNTHETIC_ENGINE_ROOT not set — cannot profile file reads",
      timings: [],
    });
  }

  // ── 1. stat() each CSV file ──────────────────────────────────
  for (const symbol of ["R_75", "R_100"] as const) {
    const csvPath = join(ENGINE_ROOT, "data", `${symbol}_ticks.csv`);
    const t0 = performance.now();
    try {
      const s = await stat(csvPath);
      timings.push({
        label: `stat:${symbol}_ticks.csv`,
        ms: +(performance.now() - t0).toFixed(2),
        bytes: s.size,
      });
    } catch {
      timings.push({
        label: `stat:${symbol}_ticks.csv`,
        ms: +(performance.now() - t0).toFixed(2),
        bytes: 0,
      });
      failures.push(`CSV not found: ${csvPath}`);
    }
  }

  // ── 2. readCsvTail simulation: full read vs tail read ────────
  for (const symbol of ["R_75", "R_100"] as const) {
    const csvPath = join(ENGINE_ROOT, "data", `${symbol}_ticks.csv`);
    if (!existsSync(csvPath)) continue;

    // Full file read (simulating cold-start cache miss)
    const t1 = performance.now();
    try {
      const content = await readFile(csvPath, "utf8");
      const lines = content.trim().split(/\r?\n/).filter(Boolean);
      const sizeBytes = content.length;
      timings.push({
        label: `readCsvTail:${symbol} (cold, full file)`,
        ms: +(performance.now() - t1).toFixed(2),
        bytes: sizeBytes,
      });

      // Simulate tail-only read (cache hit — just read new bytes)
      // Even on "tail" read, we do a stat + open + read of new bytes.
      // Here we read 0 new bytes (pure cache hit path).
      const t1b = performance.now();
      const handle = await open(csvPath, "r");
      try {
        const fileSize = sizeBytes;
        const prevOffset = fileSize; // simulate cache-hit where size == prevOffset
        const buf = Buffer.allocUnsafe(fileSize);
        const { bytesRead } = await handle.read(buf, 0, fileSize, 0);
        timings.push({
          label: `readCsvTail:${symbol} (hot, tail only)`,
          ms: +(performance.now() - t1b).toFixed(2),
          bytes: bytesRead,
        });
      } finally {
        await handle.close();
      }

      // Count lines
      const t2 = performance.now();
      const lineCount = content.split(/\r?\n/).filter(Boolean).length;
      timings.push({
        label: `countLines:${symbol}`,
        ms: +(performance.now() - t2).toFixed(2),
      });
    } catch (err) {
      timings.push({
        label: `readCsvTail:${symbol}`,
        ms: +(performance.now() - t1).toFixed(2),
      });
      failures.push(`Read CSV ${symbol} failed: ${err}`);
    }
  }

  // ── 3. Read mt5_timing.json ──────────────────────────────────
  const timingPath = join(ENGINE_ROOT, "data", "mt5_timing.json");
  if (existsSync(timingPath)) {
    const t3 = performance.now();
    try {
      const raw = await readFile(timingPath, "utf8");
      JSON.parse(raw);
      timings.push({
        label: "read+parse:mt5_timing.json",
        ms: +(performance.now() - t3).toFixed(2),
        bytes: raw.length,
      });
    } catch (err) {
      timings.push({
        label: "read+parse:mt5_timing.json (failed)",
        ms: +(performance.now() - t3).toFixed(2),
      });
      failures.push(`Parse mt5_timing.json failed: ${err}`);
    }
  } else {
    timings.push({ label: "read:mt5_timing.json (not found)", ms: 0 });
  }

  // ── 4. Read mt5_last_error.json ─────────────────────────────
  const errorPath = join(ENGINE_ROOT, "data", "mt5_last_error.json");
  if (existsSync(errorPath)) {
    const t4 = performance.now();
    try {
      const raw = await readFile(errorPath, "utf8");
      JSON.parse(raw);
      timings.push({
        label: "read+parse:mt5_last_error.json",
        ms: +(performance.now() - t4).toFixed(2),
        bytes: raw.length,
      });
    } catch (err) {
      timings.push({
        label: "read+parse:mt5_last_error.json (failed)",
        ms: +(performance.now() - t4).toFixed(2),
      });
      failures.push(`Parse mt5_last_error.json failed: ${err}`);
    }
  } else {
    timings.push({ label: "read:mt5_last_error.json (not found)", ms: 0 });
  }

  // ── 5. Read + parse + write health_history.json ──────────────
  const historyPath = join(ENGINE_ROOT, "data", "health_history.json");
  const t5 = performance.now();
  let historyBytes = 0;
  try {
    const raw = await readFile(historyPath, "utf8");
    historyBytes = raw.length;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length > 0) {
      // Simulate the append + trim + write
      parsed.push({
        timestamp: Date.now(),
        mt5_init_ms: 0,
        mt5_login_ms: 0,
        mt5_total_ms: 0,
        csv_ticks: { R_75: 0, R_100: 0 },
      });
      const trimmed = parsed.length > 60 ? parsed.slice(parsed.length - 60) : parsed;
      const t5write = performance.now();
      // Skip actual write — measure the read+parse+trim only
      timings.push({
        label: "read+parse+trim:health_history.json",
        ms: +(performance.now() - t5).toFixed(2),
        bytes: historyBytes,
      });
      timings.push({
        label: "serialize+write:health_history.json (estimated)",
        ms: +(performance.now() - t5write).toFixed(2),
      });
    } else {
      timings.push({
        label: "read+parse:health_history.json (empty array)",
        ms: +(performance.now() - t5).toFixed(2),
        bytes: historyBytes,
      });
    }
  } catch {
    timings.push({ label: "read:health_history.json (not found)", ms: 0 });
  }

  // ── 6. Read snapshot_phases.json ────────────────────────────
  const phasesPath = join(ENGINE_ROOT, "data", "snapshot_phases.json");
  if (existsSync(phasesPath)) {
    const t6 = performance.now();
    try {
      const raw = await readFile(phasesPath, "utf8");
      JSON.parse(raw);
      timings.push({
        label: "read+parse:snapshot_phases.json",
        ms: +(performance.now() - t6).toFixed(2),
        bytes: raw.length,
      });
    } catch (err) {
      timings.push({
        label: "read+parse:snapshot_phases.json (failed)",
        ms: +(performance.now() - t6).toFixed(2),
      });
      failures.push(`Parse snapshot_phases.json failed: ${err}`);
    }
  } else {
    timings.push({ label: "read:snapshot_phases.json (not found)", ms: 0 });
  }

  // ── 7. Read bridge_state.json (module init) ──────────────────
  const bridgePath = join(ENGINE_ROOT, "data", "bridge_state.json");
  if (existsSync(bridgePath)) {
    const t7 = performance.now();
    try {
      const raw = await readFile(bridgePath, "utf8");
      timings.push({
        label: "read+parse:bridge_state.json (sync, module init)",
        ms: +(performance.now() - t7).toFixed(2),
        bytes: raw.length,
      });
    } catch {
      timings.push({
        label: "read+parse:bridge_state.json (failed)",
        ms: +(performance.now() - t7).toFixed(2),
      });
    }
  } else {
    timings.push({ label: "read:bridge_state.json (not found)", ms: 0 });
  }

  // ── 8. Check actual file sizes on disk ───────────────────────
  const diskSizes: Record<string, number> = {};
  const filesToCheck = [
    `R_75_ticks.csv`,
    `R_100_ticks.csv`,
    `mt5_timing.json`,
    `mt5_last_error.json`,
    `health_history.json`,
    `snapshot_phases.json`,
    `bridge_state.json`,
  ];
  for (const file of filesToCheck) {
    const fp = join(ENGINE_ROOT, "data", file);
    try {
      const s = await stat(fp);
      diskSizes[file] = s.size;
    } catch {
      diskSizes[file] = -1;
    }
  }

  // ── Summary ──────────────────────────────────────────────────
  const totalFileIo = timings
    .filter((t) => t.ms > 0)
    .reduce((sum, t) => sum + t.ms, 0);

  const csvReadTimings = timings.filter(
    (t) => t.label.includes("readCsvTail") || t.label.includes("countLines"),
  );
  const csvReadTotal = csvReadTimings.reduce((sum, t) => sum + t.ms, 0);

  const jsonTimings = timings.filter(
    (t) => t.label.includes(".json") && t.label.includes("read"),
  );
  const jsonReadTotal = jsonTimings.reduce((sum, t) => sum + t.ms, 0);

  return NextResponse.json({
    engine_root: ENGINE_ROOT,
    timings,
    categories: {
      csv_reads: {
        total_ms: +csvReadTotal.toFixed(2),
        files: csvReadTimings.map((t) => t.label),
      },
      json_reads: {
        total_ms: +jsonReadTotal.toFixed(2),
        files: jsonTimings.map((t) => t.label),
      },
      total_file_io_ms: +totalFileIo.toFixed(2),
      // The engine version subprocess is NOT profiled here — it's a Python
      // subprocess with its own timeout (~5s on first call). It dominates
      // cold-start latency. Include it as an estimated cost.
      engine_version_subprocess_estimated_ms: 5000,
      estimated_cold_start_total_ms: +(totalFileIo + 5000).toFixed(2),
    },
    disk_sizes_bytes: diskSizes,
    failures: failures.length > 0 ? failures : undefined,
    note: "Cold-start = first request after server start. CSV byte-offset cache is empty, engine version cache is empty.",
  });
}
