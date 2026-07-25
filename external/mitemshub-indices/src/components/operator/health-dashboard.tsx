"use client";

import React, { useEffect, useState, useCallback, useRef } from "react";
import {
  evaluateHealth,
  loadThresholds,
  ms,
  saveThresholds,
  THRESHOLD_FIELDS,
  DEFAULT_THRESHOLDS,
  type HealthMetrics,
  type HealthAlert,
  type HealthStatus,
  type AlertThresholds,
} from "../../lib/health-logic";

// ── Types ──────────────────────────────────────────────────────────────

type HealthFetcher = () => Promise<HealthMetrics>;

export type HealthDashboardProps = {
  /** Seed data — when provided the component skips the initial fetch and renders this data immediately. */
  initialData?: HealthMetrics | null;
  /** Custom health-metrics fetcher — defaults to GET /api/system/health. */
  healthFetcher?: HealthFetcher;
  /** Poll interval in ms — defaults to 15000. */
  pollIntervalMs?: number;
};

function age(tsSeconds: number): string {
  const d = Date.now() / 1000 - tsSeconds;
  if (d < 0) return "just now";
  if (d < 60) return `${Math.floor(d)}s ago`;
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  return `${(d / 3600).toFixed(1)}h ago`;
}

/** Format a staleness duration from an epoch-seconds timestamp.
 *  Returns a compact string like "2h", "30m", or "47h".
 *  Returns null when the epoch is null/invalid. */
function staleness(epochSeconds: number | null | undefined): string | null {
  if (typeof epochSeconds !== "number" || !Number.isFinite(epochSeconds)) return null;
  const delta = Date.now() / 1000 - epochSeconds;
  if (delta < 0) return "future";
  if (delta < 60) return "just now";
  if (delta < 3600) return `${Math.floor(delta / 60)}m`;
  if (delta < 86_400) return `${(delta / 3600).toFixed(1)}h`;
  return `${Math.floor(delta / 3600)}h`;
}

function barWidth(pct: number): string {
  return `${Math.min(Math.max(pct, 2), 100)}%`;
}

/** Format a warmup ISO timestamp into an elapsed-time string for display.
 *  Returns "—" when the timestamp is null/invalid. */
/** Format an ISO timestamp into a human-readable elapsed-time string.
 *  Returns "Never" when the timestamp is null/invalid. */
function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "Never";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  if (diff < 0) return "Just now";
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

function formatWarmupAge(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  const elapsed = Date.now() - new Date(isoString).getTime();
  if (elapsed < 0) return "0s";
  const seconds = Math.floor(elapsed / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remSec = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remSec}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

/** Sum the values in a warmup-cache Record (per-symbol counters). */
function calcTotal(record: Record<string, number> | undefined | null): number {
  if (!record) return 0;
  return Object.values(record).reduce((a, b) => a + b, 0);
}

/** Compute hit-rate percentage from hits and misses. */
function calcPercent(hits: number, misses: number): string {
  const total = hits + misses;
  if (total === 0) return "0";
  return String(Math.round((hits / total) * 100));
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ── Gauge mini-chart ───────────────────────────────────────────────────

function GaugeBar({
  label,
  value,
  max,
  color,
  unit,
}: {
  label: string;
  value: number;
  max: number;
  color: string;
  unit?: string;
}) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="w-20 text-[var(--text-muted)] shrink-0 text-right">
        {label}
      </span>
      <div className="flex-1 h-2 rounded-full bg-[var(--line-subtle)] overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: barWidth(pct),
            background: color,
          }}
        />
      </div>
      <span className="w-16 text-[var(--text-body)] font-mono text-right shrink-0">
        {ms(value)}
        {unit ? ` ${unit}` : ""}
      </span>
    </div>
  );
}

// ── Latency sparkline ──────────────────────────────────────────────────

/** A compact SVG line chart showing MT5 total latency over the last N polls.
 *  The polyline transitions from green (fast) through amber to red (slow).
 *  Min, max, and average labels are shown below the chart. */
function LatencySparkline({ history: samples }: { history: { total_ms: number }[] }) {
  if (samples.length < 2) return null;

  const W = 280;
  const H = 44;
  const PAD = 2; // inset so dots don't clip
  const innerW = W - PAD * 2;
  const innerH = H - PAD * 2;

  const values = samples.map((s) => s.total_ms);
  const maxVal = Math.max(...values, 1);
  const minVal = Math.min(...values);
  const avgVal = values.reduce((a, b) => a + b, 0) / values.length;

  const stepX = innerW / Math.max(values.length - 1, 1);

  // Build polyline path
  let pathD = `M ${PAD} ${PAD + innerH - (values[0] / maxVal) * innerH}`;
  for (let i = 1; i < values.length; i++) {
    const x = PAD + i * stepX;
    const y = PAD + innerH - (values[i] / maxVal) * innerH;
    pathD += ` L ${x} ${y}`;
  }

  // Color: interpolate green → amber → red based on value / max
  const lineColor = maxVal > 30_000 ? "var(--accent-danger)"
    : maxVal > 15_000 ? "var(--accent-warn)"
    : "var(--accent-positive)";

  // Gridline positions (25% / 50% / 75% / 100%)
  const grids = [0.25, 0.5, 0.75, 1.0];

  return (
    <div>
      <svg
        width="100%"
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="block"
        aria-label="MT5 connection latency trend"
        role="img"
      >
        {/* Grid lines */}
        {grids.map((g) => {
          const y = PAD + innerH - g * innerH;
          return (
            <line
              key={g}
              x1={PAD}
              y1={y}
              x2={W - PAD}
              y2={y}
              stroke="var(--line-subtle)"
              strokeWidth="0.5"
            />
          );
        })}

        {/* Area fill under the line */}
        <path
          d={`${pathD} L ${PAD + (values.length - 1) * stepX} ${PAD + innerH} L ${PAD} ${PAD + innerH} Z`}
          fill={lineColor}
          fillOpacity="0.08"
        />

        {/* Polyline */}
        <path
          d={pathD}
          fill="none"
          stroke={lineColor}
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* Data dots */}
        {values.map((v, i) => {
          const x = PAD + i * stepX;
          const y = PAD + innerH - (v / maxVal) * innerH;
          return (
            <circle
              key={i}
              cx={x}
              cy={y}
              r="2"
              fill={lineColor}
            />
          );
        })}
      </svg>

      {/* Stats row */}
      <div className="flex items-center justify-between text-[10px] text-[var(--text-muted)] mt-0.5">
        <span>Min <span className="font-mono text-[var(--text-body)]">{minVal < 1000 ? `${Math.round(minVal)}ms` : `${(minVal / 1000).toFixed(1)}s`}</span></span>
        <span>Avg <span className="font-mono text-[var(--text-body)]">{avgVal < 1000 ? `${Math.round(avgVal)}ms` : `${(avgVal / 1000).toFixed(1)}s`}</span></span>
        <span>Max <span className="font-mono text-[var(--text-body)]">{maxVal < 1000 ? `${Math.round(maxVal)}ms` : `${(maxVal / 1000).toFixed(1)}s`}</span></span>
      </div>
    </div>
  );
}

// ── CSV Tick sparkline ───────────────────────────────────────────────

/** A compact SVG line chart showing CSV tick counts per symbol over time.
 *  Two polylines — one for R_75 (blue/ink), one for R_100 (green/positive).
 *  Min, max, and average labels shown below the chart per symbol. */
function TickSparkline({ history: samples }: { history: { csv_ticks: Record<string, number> }[] }) {
  if (samples.length < 2) return null;

  const W = 280;
  const H = 64;
  const PAD = 2;
  const innerW = W - PAD * 2;
  const innerH = H - PAD * 2;

  const r75Values = samples.map((s) => s.csv_ticks["R_75"] ?? 0);
  const r100Values = samples.map((s) => s.csv_ticks["R_100"] ?? 0);
  const allValues = [...r75Values, ...r100Values];
  const maxVal = Math.max(...allValues, 1);

  const stepX = innerW / Math.max(samples.length - 1, 1);

  function buildPath(values: number[]): string {
    let d = `M ${PAD} ${PAD + innerH - (values[0] / maxVal) * innerH}`;
    for (let i = 1; i < values.length; i++) {
      const x = PAD + i * stepX;
      const y = PAD + innerH - (values[i] / maxVal) * innerH;
      d += ` L ${x} ${y}`;
    }
    return d;
  }

  const r75Path = buildPath(r75Values);
  const r100Path = buildPath(r100Values);

  const r75Min = Math.min(...r75Values);
  const r75Max = Math.max(...r75Values);
  const r75Avg = r75Values.reduce((a, b) => a + b, 0) / r75Values.length;
  const r100Min = Math.min(...r100Values);
  const r100Max = Math.max(...r100Values);
  const r100Avg = r100Values.reduce((a, b) => a + b, 0) / r100Values.length;

  const grids = [0.25, 0.5, 0.75, 1.0];

  return (
    <div>
      <svg
        width="100%"
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="block"
        aria-label="CSV tick count trend by symbol"
        role="img"
      >
        {/* Grid lines */}
        {grids.map((g) => (
          <line
            key={g}
            x1={PAD}
            y1={PAD + innerH - g * innerH}
            x2={W - PAD}
            y2={PAD + innerH - g * innerH}
            stroke="var(--line-subtle)"
            strokeWidth="0.5"
          />
        ))}

        {/* R_75 polyline */}
        <path
          d={r75Path}
          fill="none"
          stroke="var(--accent-ink)"
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* R_75 data dots */}
        {r75Values.map((v, i) => {
          const x = PAD + i * stepX;
          const y = PAD + innerH - (v / maxVal) * innerH;
          return (
            <circle key={`r75-${i}`} cx={x} cy={y} r="2" fill="var(--accent-ink)" />
          );
        })}

        {/* R_100 polyline */}
        <path
          d={r100Path}
          fill="none"
          stroke="var(--accent-positive)"
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* R_100 data dots */}
        {r100Values.map((v, i) => {
          const x = PAD + i * stepX;
          const y = PAD + innerH - (v / maxVal) * innerH;
          return (
            <circle key={`r100-${i}`} cx={x} cy={y} r="2" fill="var(--accent-positive)" />
          );
        })}
      </svg>

      {/* Stats row — R_75 */}
      <div className="flex items-center justify-between text-[10px] text-[var(--text-muted)] mt-0.5">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: "var(--accent-ink)" }} />
          V75
        </span>
        <span>Min <span className="font-mono text-[var(--text-body)]">{r75Min.toLocaleString()}</span></span>
        <span>Avg <span className="font-mono text-[var(--text-body)]">{Math.round(r75Avg).toLocaleString()}</span></span>
        <span>Max <span className="font-mono text-[var(--text-body)]">{r75Max.toLocaleString()}</span></span>
      </div>

      {/* Stats row — R_100 */}
      <div className="flex items-center justify-between text-[10px] text-[var(--text-muted)] mt-0.5">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: "var(--accent-positive)" }} />
          V100
        </span>
        <span>Min <span className="font-mono text-[var(--text-body)]">{r100Min.toLocaleString()}</span></span>
        <span>Avg <span className="font-mono text-[var(--text-body)]">{Math.round(r100Avg).toLocaleString()}</span></span>
        <span>Max <span className="font-mono text-[var(--text-body)]">{r100Max.toLocaleString()}</span></span>
      </div>
    </div>
  );
}

// ── Phase Timing Waterfall ────────────────────────────────────────────

/** A horizontal waterfall bar chart showing per-call phase durations.
 *  Each phase is a colored bar proportional to its ms, stacked to show
 *  the critical path. Colors follow a light -> dark gradient so the
 *  eye reads the sequence naturally. */
function PhaseWaterfall({ phases }: { phases: Record<string, unknown> }) {
  // Phases to display in order, with display labels and colors
  const PHASE_ORDER = [
    { key: "csv_read_ms", label: "CSV Read", color: "var(--accent-neutral)" },
    { key: "tick_collect_ms", label: "Collect Ticks", color: "var(--accent-ink)" },
    { key: "append_csv_ms", label: "Append CSV", color: "var(--accent-positive)" },
    { key: "analysis_ms", label: "Analysis", color: "var(--accent-warn)" },
  ] as const;  const totalMs = phases["total_ms"];
  const total: number = typeof totalMs === "number" ? totalMs : 0;

  // Collect phase entries that exist in the data
  const entries: { key: string; label: string; ms: number; color: string }[] = [];
  for (const p of PHASE_ORDER) {
    const rawMs = phases[p.key];
    const ms = typeof rawMs === "number" ? rawMs : 0;
    if (ms > 0) {
      entries.push({ key: p.key, label: p.label, ms, color: p.color });
    }
  }

  if (entries.length === 0) return null;

  const maxTotal = Math.max(total, entries.reduce((s, e) => s + e.ms, 0));

  // Safe string extraction for metadata
  const symbolStr = typeof phases["symbol"] === "string" ? phases["symbol"] : null;
  const tradingModeStr = typeof phases["trading_mode"] === "string" ? phases["trading_mode"] : null;
  const timestampNum = typeof phases["timestamp"] === "number" ? phases["timestamp"] : null;

  return (
    <div className="space-y-1.5">
      {/* Horizontal stacked bars */}
      <div className="relative h-6 rounded-full overflow-hidden bg-[var(--line-subtle)]">
        <div className="absolute inset-0 flex">
          {entries.map((e) => {
            const pct = maxTotal > 0 ? (e.ms / maxTotal) * 100 : 0;
            return (
              <div
                key={e.key}
                className="h-full first:rounded-l-full last:rounded-r-full transition-all duration-300"
                style={{ width: `${pct}%`, background: e.color, opacity: 0.7 }}
                title={`${e.label}: ${e.ms}ms`}
              />
            );
          })}
        </div>
      </div>

      {/* Legend and per-phase ms labels */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
        {entries.map((e) => (
          <div key={e.key} className="flex items-center gap-1.5">
            <span
              className="inline-block w-2 h-2 rounded-sm shrink-0"
              style={{ background: e.color }}
            />
            <span className="text-[var(--text-muted)]">{e.label}</span>
            <span className="font-mono text-[var(--text-body)] ml-auto">
              {e.ms >= 1000 ? `${(e.ms / 1000).toFixed(1)}s` : `${e.ms}ms`}
            </span>
          </div>
        ))}
        {total > 0 && (
          <div className="flex items-center gap-1.5 col-span-2 border-t border-[var(--line-subtle)] pt-1 mt-0.5">
            <span className="text-[var(--text-muted)]">Total</span>
            <span className="font-mono text-[var(--text-body)] font-semibold ml-auto">
              {total >= 1000 ? `${(total / 1000).toFixed(1)}s` : `${total}ms`}
            </span>
          </div>
        )}
      </div>

      {/* Symbol + trading mode metadata */}
      {symbolStr && (
        <p className="text-[10px] text-[var(--text-muted)] mt-1">
          Last snapshot: {symbolStr}
          {tradingModeStr ? ` · ${tradingModeStr}` : ""}
          {timestampNum
            ? ` · ${new Date(timestampNum).toLocaleTimeString()}`
            : ""}
        </p>
      )}
    </div>
  );
}

// ── Component ──────────────────────────────────────────────────────────

export function HealthDashboard({
  initialData,
  healthFetcher,
  pollIntervalMs = 15_000,
}: HealthDashboardProps = {}) {
  const [expanded, setExpanded] = useState(false);
  const [data, setData] = useState<HealthMetrics | null>(
    initialData !== undefined ? initialData : null,
  );
  const [fetchError, setFetchError] = useState(false);
  const [warmupAge, setWarmupAge] = useState<string>(() =>
    initialData?.last_warmup_at ? formatWarmupAge(initialData.last_warmup_at) : "—",
  );
  const [tickVelocity, setTickVelocity] = useState<number | null>(null);
  const [r75Velocity, setR75Velocity] = useState<number | null>(null);
  const [r100Velocity, setR100Velocity] = useState<number | null>(null);
  const [alerts, setAlerts] = useState<HealthAlert[]>([]);
  const [healthStatus, setHealthStatus] = useState<HealthStatus>("green");
  const [configuring, setConfiguring] = useState(false);
  const [customThresholds, setCustomThresholds] = useState<AlertThresholds>(() =>
    loadThresholds(),
  );
  const [draftThresholds, setDraftThresholds] = useState<AlertThresholds | null>(null);

  // Per-symbol flat-poll counter — increments when both symbol counts are unchanged
  const flatPollCountRef = useRef(0);

  // Rolling history of per-symbol tick counts for velocity computation
  const prevRef = useRef<{
    r75: number;
    r100: number;
    ts: number;
  } | null>(null);

  // ── Health evaluator (imported pure function from health-logic.ts) ─



  // Default fetcher — real HTTP call
  const defaultHealthFetcher: HealthFetcher = useCallback(async () => {
    const res = await fetch("/api/system/health");
    if (!res.ok) throw new Error("Non-ok response");
    return res.json() as Promise<HealthMetrics>;
  }, []);

  const effectiveHealthFetcher = healthFetcher ?? defaultHealthFetcher;

  const fetchHealth = useCallback(async () => {
    try {
      const metrics = await effectiveHealthFetcher();
      setData(metrics);
      setFetchError(false);

      // Compute per-symbol CSV tick velocity (ticks / minute) from epoch-to-epoch delta
      let velocity: number | null = null;
      let r75v: number | null = null;
      let r100v: number | null = null;
      if (prevRef.current) {
        const dt = (metrics.timestamp - prevRef.current.ts) / 1000; // seconds
        if (dt > 0) {
          const r75dc = (metrics.csv_ticks["R_75"] ?? 0) - prevRef.current.r75;
          const r100dc = (metrics.csv_ticks["R_100"] ?? 0) - prevRef.current.r100;
          r75v = Math.round((r75dc / dt) * 60);
          r100v = Math.round((r100dc / dt) * 60);
          velocity = r75v + r100v;
          setR75Velocity(r75v);
          setR100Velocity(r100v);
          setTickVelocity(velocity);
        }
      }

      // Per-symbol flat detection — increment counter when both symbol
      // counts are unchanged from the previous poll; reset when either moves.
      const lastPrev = prevRef.current;
      if (lastPrev) {
        const flatPoll =
          (metrics.csv_ticks["R_75"] ?? 0) === lastPrev.r75 &&
          (metrics.csv_ticks["R_100"] ?? 0) === lastPrev.r100;
        flatPollCountRef.current = flatPoll ? flatPollCountRef.current + 1 : 0;
      }

      // Evaluate health from all three criteria (using custom thresholds if set)
      const { status, activeAlerts } = evaluateHealth(
        metrics,
        velocity,
        flatPollCountRef.current,
        customThresholds,
      );
      setHealthStatus(status);
      setAlerts(activeAlerts);

      prevRef.current = {
        r75: metrics.csv_ticks["R_75"] ?? 0,
        r100: metrics.csv_ticks["R_100"] ?? 0,
        ts: metrics.timestamp,
      };

      // health_history is populated by the backend — no in-memory ref needed
    } catch {
      setFetchError(true);
    }
  }, [effectiveHealthFetcher, customThresholds]);

  // ── Warmup-age live timer ──
  // Update on every data poll so the value is fresh immediately on expand.
  useEffect(() => {
    if (data?.last_warmup_at) {
      setWarmupAge(formatWarmupAge(data.last_warmup_at));
    }
  }, [data?.last_warmup_at]);

  // 1-second ticker — only runs when the dashboard is expanded.
  // Pausing the interval when collapsed avoids unnecessary re-renders.
  useEffect(() => {
    if (!expanded || !data?.last_warmup_at) return;
    const timer = setInterval(() => {
      setWarmupAge(formatWarmupAge(data.last_warmup_at!));
    }, 1000);
    return () => clearInterval(timer);
  }, [expanded, data?.last_warmup_at]);

  useEffect(() => {
    // Skip initial fetch when initialData was provided
    if (initialData !== undefined) return;
    void fetchHealth();
    const interval = setInterval(fetchHealth, pollIntervalMs);
    return () => clearInterval(interval);
  }, [fetchHealth, pollIntervalMs, initialData]);

  // ── Derived ──────────────────────────────────────────────────────────

  const timing = data?.mt5_timing ?? null;
  const maxTiming = timing
    ? Math.max(timing.init_ms, timing.login_ms, timing.total_ms, 1000)
    : 1000;

  const velocityLabel =
    tickVelocity !== null
      ? tickVelocity >= 0
        ? `${tickVelocity.toLocaleString()} ticks/min`
        : "—"
      : "—";

  // Health badge styling
  const healthDotColor =
    fetchError
      ? "var(--accent-danger)"
      : healthStatus === "offline"
        ? "var(--accent-warn)"
        : healthStatus === "red"
          ? "var(--accent-danger)"
          : healthStatus === "amber"
            ? "var(--accent-warn)"
            : data
              ? "var(--accent-positive)"
              : "var(--text-muted)";

  const healthBadgeClass =
    fetchError
      ? "bg-[var(--accent-danger-soft)] text-[var(--accent-danger)] border-[var(--accent-danger)]"
      : healthStatus === "offline"
        ? "bg-[var(--accent-warn-soft)] text-[var(--accent-warn)] border-[var(--accent-warn)]"
        : healthStatus === "red"
          ? "bg-[var(--accent-danger-soft)] text-[var(--accent-danger)] border-[var(--accent-danger)]"
          : healthStatus === "amber"
            ? "bg-[var(--accent-warn-soft)] text-[var(--accent-warn)] border-[var(--accent-warn)]"
            : data
              ? "bg-[var(--accent-positive-soft)] text-[var(--accent-positive)] border-[var(--accent-positive)]"
              : "bg-transparent text-[var(--text-muted)] border-[var(--line-subtle)]";

  const healthLabel =
    fetchError
      ? "Error"
      : healthStatus === "offline"
        ? "Bridge Offline"
        : healthStatus === "red"
          ? "Critical"
          : healthStatus === "amber"
            ? "Warning"
            : "OK";

  // ── Render ───────────────────────────────────────────────────────────

  return (
    <div className="surface rounded-xl mt-2">
      {/* Toggle header — wraps on mobile; Configure button sits below on small screens */}
      <div className="px-3 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          {/* Main toggle button (takes remaining width) */}
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="flex-1 min-w-0 flex items-center gap-2 text-[11px] text-[var(--text-muted)] hover:text-[var(--text-body)] transition-colors"
            aria-expanded={expanded}
            aria-label="Toggle health dashboard"
          >
            {/* Health status badge — color-coded pill */}
            <span
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold transition-colors ${
                !data && !fetchError ? "animate-pulse" : ""
              } ${healthBadgeClass}`}
              title={`Health: ${healthLabel}${alerts.length > 0 ? ` — ${alerts.length} active alert(s)` : ""}`}
            >
              <span
                className="inline-block w-1.5 h-1.5 rounded-full"
                style={{ background: healthDotColor }}
                aria-hidden="true"
              />
              {healthLabel}
            </span>
            <span className="font-medium tracking-wide uppercase">
              System Health
            </span>

            {/* Warmup age — prominent large value, subtle label underneath */}
            {data?.last_warmup_at && (
              <span className="flex flex-col items-center leading-none mx-0.5 shrink-0">
                <span className="text-[13px] font-semibold text-[var(--text-body)] tabular-nums">
                  {warmupAge}
                </span>
                <span className="text-[8px] text-[var(--text-muted)] uppercase tracking-[0.12em]">
                  ago
                </span>
              </span>
            )}

            {!expanded && data && (
              <span className="text-[10px] text-[var(--text-muted)] hidden sm:inline">
                {timing ? `${ms(timing.total_ms)} MT5` : "MT5 —"} &middot;{" "}
                {velocityLabel}
                {(alerts.length > 0 || (() => {
                  const s = staleness(data?.pipeline_diagnostics?.staleDataSince);
                  return s;
                })()) && (
                  <span className="ml-1.5">
                    {(() => {
                      const s = staleness(data?.pipeline_diagnostics?.staleDataSince);
                      if (s) {
                        return (
                          <span className="text-[var(--accent-warn)]">
                            &middot; Stale: {s}
                          </span>
                        );
                      }
                      return null;
                    })()}
                    {alerts.length > 0 && (
                      <span className="text-[var(--accent-warn)]">
                        &middot; {alerts.length} alert{alerts.length > 1 ? "s" : ""}
                      </span>
                    )}
                  </span>
                )}
              </span>
            )}
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={`ml-auto transition-transform duration-200 ${
                expanded ? "rotate-180" : ""
              }`}
              aria-hidden="true"
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>

          {/* Configure button — single instance, wraps below toggle on narrow screens via parent flex-wrap */}
          <button
            type="button"
            onClick={(e) => {
              setConfiguring((v) => !v);
              if (!configuring) {
                setDraftThresholds({ ...customThresholds });
              }
            }}
            className="shrink-0 inline-flex items-center gap-1 rounded-md border border-[var(--line-subtle)] px-1.5 py-1 text-[9px] uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-body)] hover:border-[var(--line-strong)] transition-colors"
            aria-label="Configure alert thresholds"
          >
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
            Configure
          </button>
        </div>
      </div>

      {/* Expanded content */}
      {expanded && (
        <div className="px-3 pb-3 space-y-3">
          {/* Separator */}
          <div className="h-px bg-[var(--line-subtle)]" />

          {/* Active alerts — shown only when there are any */}
          {alerts.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
                Active Alerts
              </p>
              {alerts.map((alert) => (
                <div
                  key={alert.type}
                  className={`flex items-start gap-2 rounded-lg px-2.5 py-1.5 text-[10px] leading-relaxed ${
                    alert.severity === "crit"
                      ? "bg-[var(--accent-danger-soft)] text-[var(--accent-danger)]"
                      : "bg-[var(--accent-warn-soft)] text-[var(--accent-warn)]"
                  }`}
                >
                  <span
                    className={`inline-block w-1.5 h-1.5 rounded-full mt-0.5 shrink-0 ${
                      alert.severity === "crit"
                        ? "bg-[var(--accent-danger)]"
                        : "bg-[var(--accent-warn)]"
                    }`}
                    aria-hidden="true"
                  />
                  {alert.message}
                </div>
              ))}
            </div>
          )}

          {/* ── Inline threshold editor ──────────────────────────── */}
          {configuring && (
            <div className="space-y-2 rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] p-2.5">
              <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
                Alert Thresholds
              </p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                {THRESHOLD_FIELDS.map((field) => {
                  const draft = draftThresholds ?? customThresholds;
                  const value = draft[field.key];
                  return (
                    <label
                      key={field.key}
                      className="flex flex-col gap-0.5 text-[10px]"
                    >
                      <span className="text-[var(--text-body)] font-medium">
                        {field.label}
                      </span>
                      <span className="text-[var(--text-muted)] text-[9px]">
                        {field.hint}
                      </span>
                      <div className="flex items-center gap-1">
                        <input
                          type="number"
                          min={field.min}
                          step={field.step}
                          value={value}
                          onChange={(e) => {
                            const n = Number(e.target.value);
                            if (!Number.isFinite(n)) return;
                            setDraftThresholds((prev) => ({
                              ...(prev ?? customThresholds),
                              [field.key]: n,
                            }));
                          }}
                          className="w-full rounded border border-[var(--line-subtle)] bg-[var(--bg-panel-strong)] px-1.5 py-1 text-[11px] font-mono text-[var(--text-strong)] outline-none focus:border-[var(--accent-ink)] transition-colors"
                        />
                        <span className="text-[var(--text-muted)] shrink-0 w-8 text-right">
                          {field.suffix}
                        </span>
                      </div>
                    </label>
                  );
                })}
              </div>
              {/* Save / Cancel / Reset actions */}
              <div className="flex items-center justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => {
                    setDraftThresholds(null);
                    setConfiguring(false);
                  }}
                  className="rounded-md border border-[var(--line-subtle)] px-2 py-1 text-[10px] text-[var(--text-muted)] hover:text-[var(--text-body)] hover:border-[var(--line-strong)] transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCustomThresholds({ ...DEFAULT_THRESHOLDS });
                    saveThresholds(DEFAULT_THRESHOLDS);
                    setDraftThresholds(null);
                    setConfiguring(false);
                  }}
                  className="rounded-md border border-[var(--line-subtle)] px-2 py-1 text-[10px] text-[var(--text-muted)] hover:text-[var(--accent-warn)] hover:border-[var(--accent-warn)] transition-colors"
                >
                  Reset Defaults
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const final = draftThresholds ?? customThresholds;
                    setCustomThresholds(final);
                    saveThresholds(final);
                    setDraftThresholds(null);
                    setConfiguring(false);
                  }}
                  className="rounded-md bg-[var(--accent-ink)] px-2.5 py-1 text-[10px] font-medium text-white hover:bg-[var(--accent-ink-hover)] transition-colors"
                >
                  Save
                </button>
              </div>
            </div>
          )}

          {/* ── MT5 Connection Diagnostics ────────────────────────────── */}
          <div className="space-y-2">
            <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
              MT5 Connection Diagnostics
            </p>

            {/* Connection status row */}
            <div className="flex items-center gap-3 text-[11px]">
              <span className="w-20 text-[var(--text-muted)] shrink-0 text-right">Status</span>
              <span className="flex items-center gap-1.5">
                <span
                  className={`inline-block w-2 h-2 rounded-full ${
                    data?.mt5_process_running
                      ? "bg-[var(--accent-positive)]"
                      : data?.mt5_configured
                        ? "bg-[var(--accent-danger)]"
                        : "bg-[var(--text-muted)]"
                  }`}
                  aria-hidden="true"
                />
                <span className={
                  data?.mt5_process_running
                    ? "text-[var(--accent-positive)] font-medium"
                    : data?.mt5_configured
                      ? "text-[var(--accent-danger)] font-medium"
                      : "text-[var(--text-muted)]"
                }>
                  {data?.mt5_process_running
                    ? "Connected"
                    : data?.mt5_configured
                      ? "Terminal not running"
                      : "Not configured"}
                </span>
              </span>
            </div>

            {/* Server */}
            {data?.mt5_server && (
              <div className="flex items-center gap-3 text-[11px]">
                <span className="w-20 text-[var(--text-muted)] shrink-0 text-right">Server</span>
                <span className="font-mono text-[var(--text-body)]">{data.mt5_server}</span>
              </div>
            )}

            {/* Last connected */}
            {data?.mt5_last_connected_at && (
              <div className="flex items-center gap-3 text-[11px]">
                <span className="w-20 text-[var(--text-muted)] shrink-0 text-right">Last OK</span>
                <span className="text-[var(--text-body)]">{formatTimestamp(data.mt5_last_connected_at)}</span>
              </div>
            )}

            {/* Last error — shown prominently when present */}
            {data?.mt5_error && (
              <div className="rounded-lg bg-[var(--accent-danger-soft)] border border-[rgba(196,68,58,0.15)] px-2.5 py-2">
                <div className="flex items-start gap-2">
                  <span className="inline-block w-2 h-2 rounded-full bg-[var(--accent-danger)] mt-0.5 shrink-0" aria-hidden="true" />
                  <div className="min-w-0 flex-1">
                    <p className="text-[10px] font-semibold text-[var(--accent-danger)] mb-0.5">Last Error</p>
                    <p className="text-[10px] text-[var(--accent-danger)] leading-relaxed break-words">
                      {data.mt5_error}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Last test result */}
            {data?.mt5_last_test && (
              <div className="flex items-center gap-3 text-[11px]">
                <span className="w-20 text-[var(--text-muted)] shrink-0 text-right">Last Test</span>
                <span className="flex items-center gap-1.5">
                  <span
                    className={`inline-block w-1.5 h-1.5 rounded-full ${
                      data.mt5_last_test.success
                        ? "bg-[var(--accent-positive)]"
                        : "bg-[var(--accent-danger)]"
                    }`}
                  />
                  <span className={data.mt5_last_test.success ? "text-[var(--accent-positive)]" : "text-[var(--accent-danger)]"}>
                    {data.mt5_last_test.success ? "OK" : "Failed"}
                  </span>
                  <span className="text-[var(--text-muted)]">
                    {data.mt5_last_test.duration_ms}ms
                    {data.mt5_last_test.account_name ? ` · ${data.mt5_last_test.account_name}` : ""}
                    {data.mt5_last_test.account_balance != null ? ` · $${data.mt5_last_test.account_balance.toLocaleString()}` : ""}
                  </span>
                </span>
              </div>
            )}

            {/* No data state */}
            {!data?.mt5_configured && !data?.mt5_error && !data?.mt5_last_test && (
              <p className="text-[10px] text-[var(--text-muted)] italic">
                MT5 is not configured. Set SYNTHETIC_MT5_SERVER / LOGIN / PASSWORD in .env.local.
              </p>
            )}
          </div>

          {/* MT5 Connection Timing */}
          {timing && (
            <div className="space-y-1">
              <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
                MT5 Connection Latency
              </p>
              <GaugeBar
                label="Initialize"
                value={timing.init_ms}
                max={maxTiming}
                color="var(--accent-ink)"
              />
              <GaugeBar
                label="Login"
                value={timing.login_ms}
                max={maxTiming}
                color="var(--accent-positive)"
              />
              <GaugeBar
                label="Total"
                value={timing.total_ms}
                max={maxTiming}
                color="var(--accent-warn)"
              />
              <p className="text-[10px] text-[var(--text-muted)] mt-1">
                Last check: {age(timing.timestamp)}
              </p>

              {/* ── Latency sparkline (from backend-persisted health_history) ─── */}
              {data?.health_history && data.health_history.length >= 2 && (
                <div className="mt-3">
                  <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium mb-1.5">
                    Latency Trend (last {data.health_history.length} polls)
                  </p>
                  <LatencySparkline history={data.health_history.map(s => ({ total_ms: s.mt5_total_ms }))} />
                </div>
              )}
            </div>
          )}

          {/* Snapshot Phase Waterfall */}
          {data?.snapshot_phases && (
            <div className="space-y-1">
              <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
                Call Phase Breakdown
              </p>
              <PhaseWaterfall phases={data.snapshot_phases} />
            </div>
          )}

          {/* CSV Data Pipeline */}
          <div className="space-y-1">
            <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
              CSV Tick Pipeline
            </p>

            {/* R_75 lane */}
            <div className="flex items-center gap-3 text-[11px]">
              <span className="w-20 text-[var(--text-muted)] shrink-0 text-right font-medium">
                V75
              </span>
              <span className="font-mono text-[var(--text-body)] min-w-[6rem]">
                {(data?.csv_ticks["R_75"] ?? 0).toLocaleString()} ticks
              </span>
              <span className="font-mono text-[var(--text-muted)] text-[10px]">
                {r75Velocity !== null ? `${r75Velocity.toLocaleString()}/min` : "—"}
              </span>
              {r75Velocity !== null && r75Velocity > 0 && (
                <span
                  className={`inline-block w-1.5 h-1.5 rounded-full ${
                    r75Velocity >= 25
                      ? "bg-[var(--accent-positive)]"
                      : r75Velocity >= 5
                        ? "bg-[var(--accent-warn)]"
                        : "bg-[var(--accent-danger)]"
                  }`}
                  title={`${r75Velocity} ticks/min — ${r75Velocity >= 25 ? "healthy" : r75Velocity >= 5 ? "moderate" : "slow"}`}
                />
              )}
            </div>

            {/* R_100 lane */}
            <div className="flex items-center gap-3 text-[11px]">
              <span className="w-20 text-[var(--text-muted)] shrink-0 text-right font-medium">
                V100
              </span>
              <span className="font-mono text-[var(--text-body)] min-w-[6rem]">
                {(data?.csv_ticks["R_100"] ?? 0).toLocaleString()} ticks
              </span>
              <span className="font-mono text-[var(--text-muted)] text-[10px]">
                {r100Velocity !== null ? `${r100Velocity.toLocaleString()}/min` : "—"}
              </span>
              {r100Velocity !== null && r100Velocity > 0 && (
                <span
                  className={`inline-block w-1.5 h-1.5 rounded-full ${
                    r100Velocity >= 25
                      ? "bg-[var(--accent-positive)]"
                      : r100Velocity >= 5
                        ? "bg-[var(--accent-warn)]"
                        : "bg-[var(--accent-danger)]"
                  }`}
                  title={`${r100Velocity} ticks/min — ${r100Velocity >= 25 ? "healthy" : r100Velocity >= 5 ? "moderate" : "slow"}`}
                />
              )}
            </div>

            {/* Aggregate velocity (collapsed label) */}
            <div className="flex items-center gap-3 text-[11px]">
              <span className="w-20 text-[var(--text-muted)] shrink-0 text-right">
                Total
              </span>
              <span className="font-mono text-[var(--text-body)] min-w-[6rem]">
                {(data ? Object.values(data.csv_ticks).reduce((a, b) => a + b, 0).toLocaleString() : "0")} ticks
              </span>
              <span className="font-mono text-[var(--text-muted)] text-[10px]">
                {velocityLabel}
              </span>
              {tickVelocity !== null && tickVelocity > 0 && (
                <span
                  className={`inline-block w-1.5 h-1.5 rounded-full ${
                    tickVelocity >= 50
                      ? "bg-[var(--accent-positive)]"
                      : tickVelocity >= 10
                        ? "bg-[var(--accent-warn)]"
                        : "bg-[var(--accent-danger)]"
                  }`}
                  title={`${tickVelocity} ticks/min total`}
                />
              )}
            </div>

            {/* ── CSV Tick sparkline ──────────────────────────────── */}
            {data?.health_history && data.health_history.length >= 2 && (
              <div className="mt-3">
                <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium mb-1.5">
                  Tick Count Trend (last {data.health_history.length} samples)
                </p>
                <TickSparkline history={data.health_history} />
              </div>
            )}

            <GaugeBar
              label="Size"
              value={data?.csv_size_bytes ?? 0}
              max={Math.max(data?.csv_size_bytes ?? 1, 1)}
              color="var(--accent-neutral)"
              unit={data ? formatBytes(data.csv_size_bytes) : ""}
            />
          </div>

          {/* Engine Info */}
          <div className="flex items-center gap-4 text-[11px] text-[var(--text-muted)]">
            {data?.engine_version && (
              <span>
                Engine:{" "}
                <span className="font-mono text-[var(--text-body)]">
                  v{data.engine_version}
                </span>
              </span>
            )}
            {data?.csv_ticks && (
              <span>
                Polled:{" "}
                <span className="text-[var(--text-body)]">
                  {new Date(data.timestamp).toLocaleTimeString()}
                </span>
              </span>
            )}
            {/* CSV byte-offset cache hit ratio */}
            {data && (
              <span className="text-[var(--text-body)]">
                CSV Cache:{" "}
                <span className="font-mono">
                  {Math.round(data.csv_cache_hit_ratio * 100)}%
                </span>
              </span>
            )}
            {/* Warmup cache hit/miss ratio */}
            {calcTotal(data?.warmup_cache_hits) + calcTotal(data?.warmup_cache_misses) > 0 && (
              <span>
                Warmup Cache:{" "}
                <span className="font-mono text-[var(--text-body)]">
                  {data!.warmup_cache_hits.R_75 ?? 0} hit / {data!.warmup_cache_misses.R_75 ?? 0} miss (V75) &middot; {data!.warmup_cache_hits.R_100 ?? 0} hit / {data!.warmup_cache_misses.R_100 ?? 0} miss (V100)
                </span>
                <span className="ml-1 text-[var(--text-muted)]">
                  (V75 hit rate: {calcPercent(data!.warmup_cache_hits.R_75 ?? 0, data!.warmup_cache_misses.R_75 ?? 0)}% &middot; V100 hit rate: {calcPercent(data!.warmup_cache_hits.R_100 ?? 0, data!.warmup_cache_misses.R_100 ?? 0)}%)
                </span>
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
