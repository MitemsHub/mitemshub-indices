"use client";

import React, { useEffect, useState, useCallback } from "react";

// ── Types ────────────────────────────────────────────────────────

type HorizonForecast = {
  symbol: string;
  horizon_sec: number;
  timeframe_sec: number;
  bars: number;
  current_close: number;
  current_sigma: number;
  projected_sigma_avg: number;
  projected_sigma_end: number;
  long_run_sigma: number;
  range_p50_price: number;
  range_p90_price: number;
  expected_low_p50: number;
  expected_high_p50: number;
  expected_low_p90: number;
  expected_high_p90: number;
  vol_trend: string;
  persistence: number;
  drift_events: number;
  steps_since_drift: number;
  regime_stable: boolean;
  confidence: number;
  notes: string[];
};

type HorizonValidation = {
  symbol: string;
  horizon_sec: number;
  timeframe_sec: number;
  windows: number;
  coverage_p50: number;
  coverage_p90: number;
  median_realized_ratio: number;
  mean_realized_ratio: number;
  over_forecast_pct: number;
  drift_events: number;
  fitted_p50_mult: number;
  fitted_p90_mult: number;
};

type HorizonEntry = {
  horizon_sec: number;
  verdict: string;
  validation: HorizonValidation;
  forecast: HorizonForecast;
};

type SymbolHorizon = {
  symbol: string;
  timeframe_sec: number;
  tick_csv: string | null;
  ticks: number | null;
  garch_calibrated: boolean | null;
  error: string | null;
  horizons: Record<string, HorizonEntry>;
};

type HorizonStatsResponse = Record<string, SymbolHorizon>;

// ── Formatting helpers ───────────────────────────────────────────

function fmtPrice(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value <= 0) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function fmtPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

function StatCard({
  label,
  value,
  subtitle,
  color,
}: {
  label: string;
  value: string;
  subtitle?: string;
  color?: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2.5 py-2">
      <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium mb-1">
        {label}
      </p>
      <p className={`text-lg font-bold font-mono ${color || "text-[var(--text-strong)]"}`}>
        {value}
      </p>
      {subtitle && (
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{subtitle}</p>
      )}
    </div>
  );
}

function CoverageBar({ value }: { value: number }) {
  const pct = Math.min(Math.max(value * 100, 0), 100);
  const color =
    value >= 0.35 && value <= 0.65
      ? "bg-[var(--accent-positive)]"
      : value >= 0.25 && value <= 0.75
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

function VerdictBadge({ verdict }: { verdict: string }) {
  const calibrated = verdict === "calibrated";
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

// ── Horizon card (one symbol × one horizon) ──────────────────────

function HorizonCard({
  label,
  entry,
}: {
  label: string;
  entry: HorizonEntry | undefined;
}) {
  if (!entry) {
    return (
      <div className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] p-3">
        <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium mb-1">
          {label}
        </p>
        <p className="text-[11px] text-[var(--text-muted)]">No forecast</p>
      </div>
    );
  }

  const fc = entry.forecast;
  const val = entry.validation;
  const p50Pct =
    fc.current_close > 0 && fc.range_p50_price > 0
      ? (fc.range_p50_price / fc.current_close) * 100
      : null;
  const p90Pct =
    fc.current_close > 0 && fc.range_p90_price > 0
      ? (fc.range_p90_price / fc.current_close) * 100
      : null;

  const trendColor =
    fc.vol_trend === "falling"
      ? "text-[var(--accent-positive)]"
      : fc.vol_trend === "rising"
        ? "text-[var(--accent-warn)]"
        : "text-[var(--text-muted)]";

  return (
    <div className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] p-3 space-y-2.5">
      <div className="flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
          {label}
        </p>
        <VerdictBadge verdict={entry.verdict} />
      </div>

      {/* Vol bands */}
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-md bg-[var(--bg-canvas)] border border-[var(--line-subtle)] px-2 py-1.5">
          <p className="text-[9px] uppercase tracking-[0.14em] text-[var(--text-label)] font-medium">
            p50 Range (median)
          </p>
          <p className="text-sm font-bold font-mono text-[var(--text-strong)]">
            {fmtPrice(fc.expected_low_p50)} – {fmtPrice(fc.expected_high_p50)}
          </p>
          <p className="text-[10px] text-[var(--text-muted)]">
            ±{p50Pct != null ? fmtNum(p50Pct / 2, 2) : "—"}% around {fmtPrice(fc.current_close)}
          </p>
        </div>
        <div className="rounded-md bg-[var(--bg-canvas)] border border-[var(--line-subtle)] px-2 py-1.5">
          <p className="text-[9px] uppercase tracking-[0.14em] text-[var(--text-label)] font-medium">
            p90 Range (extreme)
          </p>
          <p className="text-sm font-bold font-mono text-[var(--text-strong)]">
            {fmtPrice(fc.expected_low_p90)} – {fmtPrice(fc.expected_high_p90)}
          </p>
          <p className="text-[10px] text-[var(--text-muted)]">
            ±{p90Pct != null ? fmtNum(p90Pct / 2, 2) : "—"}% around {fmtPrice(fc.current_close)}
          </p>
        </div>
      </div>

      {/* Volatility state */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <StatCard
          label="Vol Trend"
          value={fc.vol_trend || "—"}
          subtitle={`persistence ${fmtNum(fc.persistence, 3)}`}
          color={trendColor}
        />
        <StatCard
          label="Regime"
          value={fc.regime_stable ? "Stable" : "Transitioning"}
          subtitle={`${fc.drift_events} drift event${fc.drift_events === 1 ? "" : "s"}`}
          color={fc.regime_stable ? "text-[var(--accent-positive)]" : "text-[var(--accent-warn)]"}
        />
        <StatCard
          label="Forecast σ"
          value={fmtNum(fc.projected_sigma_avg, 4)}
          subtitle={`now ${fmtNum(fc.current_sigma, 4)} · long-run ${fmtNum(fc.long_run_sigma, 4)}`}
          color="text-[var(--accent-ink)]"
        />
        <StatCard
          label="Confidence"
          value={fmtPct(fc.confidence)}
          subtitle={`${fc.bars} bars (${(fc.horizon_sec / 3600).toFixed(0)}h)`}
          color="text-[var(--accent-ink)]"
        />
      </div>

      {/* Calibration */}
      <div className="space-y-1.5">
        <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
          Walk-Forward Calibration
        </p>
        <div className="grid grid-cols-2 gap-2 text-[11px]">
          <div>
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-[var(--text-muted)]">p50 coverage</span>
              <span className="font-mono text-[var(--text-body)]">{fmtPct(val.coverage_p50)}</span>
            </div>
            <CoverageBar value={val.coverage_p50} />
          </div>
          <div>
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-[var(--text-muted)]">p90 coverage</span>
              <span className="font-mono text-[var(--text-body)]">{fmtPct(val.coverage_p90)}</span>
            </div>
            <CoverageBar value={val.coverage_p90 / 0.9} />
          </div>
        </div>
        <p className="text-[10px] text-[var(--text-muted)] font-mono">
          {val.windows} windows · fitted ×{fmtNum(val.fitted_p50_mult, 2)} / ×{fmtNum(val.fitted_p90_mult, 2)} · over-forecast {fmtPct(val.over_forecast_pct)}
        </p>
      </div>
    </div>
  );
}

// ── Panel ────────────────────────────────────────────────────────

export function HorizonForecastPanel({
  fetcher,
  pollIntervalMs = 15_000,
}: {
  fetcher?: () => Promise<HorizonStatsResponse>;
  pollIntervalMs?: number;
}) {
  const [data, setData] = useState<HorizonStatsResponse | null>(null);
  const [fetchError, setFetchError] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      let result: HorizonStatsResponse;
      if (fetcher) {
        result = await fetcher();
      } else {
        const res = await fetch("/api/system/forecast-horizon");
        if (!res.ok) throw new Error(`forecast-horizon ${res.status}`);
        result = (await res.json()) as HorizonStatsResponse;
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

  // Collapsed summary: any calibrated horizon? windows count?
  const symbols = data ? Object.entries(data) : [];
  const anyCalibrated = symbols.some(
    ([, s]) =>
      !s.error &&
      Object.values(s.horizons || {}).some((h) => h.verdict === "calibrated"),
  );
  const totalWindows = symbols.reduce(
    (sum, [, s]) =>
      sum +
      Object.values(s.horizons || {}).reduce(
        (hSum, h) => hSum + (h.validation?.windows || 0),
        0,
      ),
    0,
  );

  const hasData = symbols.length > 0 && !fetchError;

  return (
    <div className="surface rounded-xl mt-2">
      {/* Toggle header */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-[11px] text-[var(--text-muted)] hover:text-[var(--text-body)] transition-colors"
        aria-expanded={expanded}
        aria-label="Toggle horizon forecast"
      >
        <span className="flex items-center gap-2">
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              fetchError
                ? "bg-[var(--accent-danger)]"
                : anyCalibrated
                  ? "bg-[var(--accent-positive)]"
                  : hasData
                    ? "bg-[var(--accent-warn)]"
                    : "bg-[var(--text-muted)]"
            }`}
            aria-hidden="true"
          />
          <span className="font-medium tracking-wide uppercase">
            Horizon Volatility Forecast
          </span>
          {!expanded && hasData && (
            <span className="text-[10px] text-[var(--text-muted)]">
              {anyCalibrated
                ? "calibrated"
                : `needs data · ${totalWindows} windows`}
            </span>
          )}
        </span>
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
          aria-hidden="true"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="px-3 pb-3 space-y-3">
          <div className="h-px bg-[var(--line-subtle)]" />

          {fetchError ? (
            <p className="text-[11px] text-[var(--accent-danger)]">
              Horizon forecast unavailable. Run the engine bridge to populate.
            </p>
          ) : !data ? (
            <div className="flex items-center gap-2 text-[11px] text-[var(--text-muted)]">
              <div className="w-2 h-2 rounded-full bg-[var(--line-subtle)] animate-pulse" />
              Loading horizon forecast...
            </div>
          ) : (
            <>
              {/* Intro copy */}
              <p className="text-[11px] text-[var(--text-muted)] leading-relaxed">
                Volatility regime over the next 4–6 hours from the calibrated
                EGARCH projection + ADWIN drift state. Synthetic indices are
                direction-unpredictable — this is the honest, calibrated
                forecast of how far price is expected to range.
              </p>

              {symbols.map(([symbol, s]) => {
                if (s.error) {
                  return (
                    <div
                      key={symbol}
                      className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] p-3"
                    >
                      <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium mb-1">
                        {symbol.replace("R_", "V")}
                      </p>
                      <p className="text-[11px] text-[var(--accent-danger)]">
                        {s.error === "no_tick_csv"
                          ? "No tick data on disk — collect or backfill data first."
                          : s.error === "insufficient_ticks"
                            ? `Only ${s.ticks} ticks — need at least 200 for a meaningful forecast.`
                            : s.error}
                      </p>
                    </div>
                  );
                }

                const entries = Object.entries(s.horizons || {});
                return (
                  <div key={symbol} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-strong)]">
                        {symbol.replace("R_", "V")}
                      </p>
                      <span className="text-[10px] text-[var(--text-muted)] font-mono">
                        {s.ticks?.toLocaleString("en-US") ?? "—"} ticks · {s.garch_calibrated ? "calibrated EGARCH" : "default EGARCH"}
                      </span>
                    </div>
                    <div className="grid gap-2 md:grid-cols-2">
                      {entries.map(([label, entry]) => (
                        <HorizonCard key={label} label={label} entry={entry} />
                      ))}
                    </div>
                  </div>
                );
              })}

              {symbols.length === 0 && (
                <p className="text-[11px] text-[var(--text-muted)] italic text-center py-2">
                  No horizon forecast data yet.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
