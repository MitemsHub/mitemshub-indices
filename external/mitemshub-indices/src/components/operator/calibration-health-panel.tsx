"use client";

import React, { useEffect, useState, useCallback } from "react";

// ── Types (mirror Python calibration_health.get_calibration_health) ──

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

type CalibrationHealthResponse = Record<string, SymbolCalibrationHealth>;

// ── Formatting helpers ───────────────────────────────────────────

function fmtPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function fmtNum(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return String(Math.round(value));
}

function VerdictBadge({ verdict }: { verdict: string | null }) {
  const calibrated = verdict === "calibrated";
  if (!verdict) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide bg-[var(--line-subtle)]/40 text-[var(--text-muted)] border border-[var(--line-subtle)]">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--text-muted)]" aria-hidden="true" />
        No data
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
        calibrated
          ? "bg-[var(--accent-positive)]/10 text-[var(--accent-positive)] border border-[var(--accent-positive)]/25"
          : "bg-[var(--accent-warn)]/10 text-[var(--accent-warn)] border border-[var(--accent-warn)]/25"
      }`}
    >
      <span
        className={`inline-block w-1.5 h-1.5 rounded-full ${
          calibrated ? "bg-[var(--accent-positive)]" : "bg-[var(--accent-warn)]"
        }`}
        aria-hidden="true"
      />
      {calibrated ? "Calibrated" : "Needs data"}
    </span>
  );
}

function CoverageBar({ value, target }: { value: number | null; target: number }) {
  if (value == null || !Number.isFinite(value)) {
    return <div className="h-1.5 rounded-full bg-[var(--line-subtle)]" />;
  }
  const pct = Math.min(Math.max((value / target) * 100, 0), 100);
  const color =
    Math.abs(value - target) <= 0.1
      ? "bg-[var(--accent-positive)]"
      : Math.abs(value - target) <= 0.2
        ? "bg-[var(--accent-warn)]"
        : "bg-[var(--accent-danger)]";
  return (
    <div className="h-1.5 rounded-full bg-[var(--line-subtle)] overflow-hidden">
      <div
        className={`h-full rounded-full ${color} transition-all duration-500`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// ── Per-symbol card ─────────────────────────────────────────────

function SymbolCard({ symbol, health }: { symbol: string; health: SymbolCalibrationHealth }) {
  const horizons = health.horizons || {};
  return (
    <div className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] p-3 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-[var(--text-strong)]">{symbol}</p>
        {!health.cache_fresh && (
          <span className="text-[10px] text-[var(--accent-warn)] font-medium">
            horizon cache stale — run forecast-horizon
          </span>
        )}
      </div>

      {/* Horizon validation */}
      <div className="grid grid-cols-2 gap-2">
        {["4h", "6h"].map((label) => {
          const h = horizons[label];
          return (
            <div key={label} className="rounded-md bg-[var(--bg-canvas)] border border-[var(--line-subtle)] px-2 py-1.5 space-y-1.5">
              <div className="flex items-center justify-between">
                <p className="text-[10px] uppercase tracking-[0.14em] text-[var(--text-label)] font-medium">
                  {label} horizon
                </p>
                <VerdictBadge verdict={h?.verdict ?? null} />
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-[var(--text-muted)]">p50 coverage</span>
                  <span className="font-mono text-[var(--text-body)]">{fmtPct(h?.coverage_p50)}</span>
                </div>
                <CoverageBar value={h?.coverage_p50 ?? null} target={0.5} />
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-[var(--text-muted)]">p90 coverage</span>
                  <span className="font-mono text-[var(--text-body)]">{fmtPct(h?.coverage_p90)}</span>
                </div>
                <CoverageBar value={h?.coverage_p90 ?? null} target={0.9} />
              </div>
              <p className="text-[10px] text-[var(--text-muted)] font-mono">
                {h?.windows != null ? `${fmtNum(h.windows)} windows` : "no walk-forward"}
              </p>
            </div>
          );
        })}
      </div>

      {/* Per-trigger-type hit rates */}
      <div>
        <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium mb-1.5">
          Target-hit rates by trigger
        </p>
        {health.triggers.length === 0 ? (
          <p className="text-[11px] text-[var(--text-muted)]">
            No scored outcomes yet — run score-live-calibration to build evidence.
          </p>
        ) : (
          <div className="overflow-hidden rounded-md border border-[var(--line-subtle)]">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="bg-[var(--bg-canvas)] text-[var(--text-label)]">
                  <th className="text-left font-medium px-2 py-1.5">Trigger</th>
                  <th className="text-right font-medium px-2 py-1.5">n</th>
                  <th className="text-right font-medium px-2 py-1.5">Target</th>
                  <th className="text-right font-medium px-2 py-1.5">Stop</th>
                </tr>
              </thead>
              <tbody>
                {health.triggers.map((t) => {
                  const rateOk = t.enough_samples && t.target_hit_rate >= 0.5;
                  const rateColor = !t.enough_samples
                    ? "text-[var(--text-muted)]"
                    : t.suppressed
                      ? "text-[var(--accent-danger)]"
                      : rateOk
                        ? "text-[var(--accent-positive)]"
                        : "text-[var(--accent-warn)]";
                  return (
                    <tr key={t.trigger_type} className="border-t border-[var(--line-subtle)]">
                      <td className="px-2 py-1.5 text-[var(--text-body)]">
                        {t.trigger_type}
                        {!t.enough_samples && (
                          <span className="ml-1 text-[9px] text-[var(--text-muted)]">(few)</span>
                        )}
                        {t.suppressed && (
                          <span className="ml-1.5 inline-flex items-center rounded-full bg-[var(--accent-danger)]/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-[var(--accent-danger)]">
                            suppressed
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono text-[var(--text-muted)]">{t.count}</td>
                      <td className={`px-2 py-1.5 text-right font-mono ${rateColor}`}>
                        {fmtPct(t.target_hit_rate)}
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono text-[var(--text-muted)]">
                        {fmtPct(t.stop_hit_rate)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Panel ────────────────────────────────────────────────────────

export function CalibrationHealthPanel({
  fetcher,
  pollIntervalMs = 15_000,
}: {
  fetcher?: () => Promise<CalibrationHealthResponse>;
  pollIntervalMs?: number;
}) {
  const [data, setData] = useState<CalibrationHealthResponse | null>(null);
  const [fetchError, setFetchError] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      let result: CalibrationHealthResponse;
      if (fetcher) {
        result = await fetcher();
      } else {
        const res = await fetch("/api/system/calibration-health");
        if (!res.ok) throw new Error(`calibration-health ${res.status}`);
        result = (await res.json()) as CalibrationHealthResponse;
      }
      setData(result);
      setFetchError(false);
    } catch {
      setFetchError(true);
    }
  }, [fetcher]);

  useEffect(() => {
    void fetchData();
    const interval = setInterval(() => void fetchData(), pollIntervalMs);
    return () => clearInterval(interval);
  }, [fetchData, pollIntervalMs]);

  // Collapsed summary: any calibrated horizon? total scored triggers?
  const symbols = data ? Object.entries(data) : [];
  const anyCalibrated = symbols.some(
    ([, s]) => Object.values(s.horizons || {}).some((h) => h.verdict === "calibrated"),
  );
  const totalScored = symbols.reduce(
    (sum, [, s]) => sum + (s.triggers || []).reduce((acc, t) => acc + t.count, 0),
    0,
  );

  return (
    <section className="rounded-2xl border border-[var(--line-subtle)] bg-[var(--bg-panel)] p-4">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span className="flex items-center gap-2">
          <span className="text-sm font-semibold text-[var(--text-strong)]">Calibration health</span>
          {anyCalibrated ? (
            <span className="rounded-full bg-[var(--accent-positive)]/10 text-[var(--accent-positive)] border border-[var(--accent-positive)]/25 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide">
              Calibrated
            </span>
          ) : (
            <span className="rounded-full bg-[var(--accent-warn)]/10 text-[var(--accent-warn)] border border-[var(--accent-warn)]/25 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide">
              Building evidence
            </span>
          )}
        </span>
        <span className="text-[11px] text-[var(--text-muted)] font-mono">
          {fetchError ? "offline" : `${totalScored} scored`}
          <span className="ml-2 inline-block transition-transform" style={{ transform: expanded ? "rotate(180deg)" : "none" }}>
            ▾
          </span>
        </span>
      </button>

      {expanded && (
        <div className="mt-3 space-y-3">
          {fetchError && (
            <p className="text-[11px] text-[var(--accent-danger)]">
              Calibration health unavailable — engine bridge offline.
            </p>
          )}
          {!fetchError && symbols.length === 0 && (
            <p className="text-[11px] text-[var(--text-muted)]">No calibration data yet.</p>
          )}
          {symbols.map(([symbol, health]) => (
            <SymbolCard key={symbol} symbol={symbol} health={health} />
          ))}
        </div>
      )}
    </section>
  );
}
