"use client";

import React, { useMemo, useState } from "react";
import type { ConfidenceTrend } from "../../lib/contracts";
import { ConfidenceSparkline } from "./ConfidenceSparkline";

/* ──────────────────────────────────────────────────────────────
   Types
   ────────────────────────────────────────────────────────────── */

type Regime = "trend_up" | "trend_down" | "range" | "volatile" | "compression";

export interface TradeRecord {
  id: string;
  symbol: "R_75" | "R_100";
  direction: "buy" | "sell";
  entry: number;
  exit: number;
  rMultiple: number;
  pnl: number;
  win: boolean;
  regime: Regime;
  timestamp: string;
  confidenceAtEntry: number;
  holdMinutes: number;
  outcome: "win" | "loss" | "breakeven";
}

interface RegimeStats {
  trades: number;
  wins: number;
  losses: number;
  winRate: number;
  avgR: number;
  totalPnl: number;
}

/* ──────────────────────────────────────────────────────────────
   Filter constants
   ────────────────────────────────────────────────────────────── */

const REGIMES: Regime[] = ["trend_up", "trend_down", "range", "volatile", "compression"];

/* ──────────────────────────────────────────────────────────────
   Derived stats
   ────────────────────────────────────────────────────────────── */

function computeStats(trades: TradeRecord[]) {
  const total = trades.length;
  const wins = trades.filter((t) => t.outcome === "win").length;
  const losses = trades.filter((t) => t.outcome === "loss").length;
  const winRate = total > 0 ? wins / total : 0;
  const totalR = trades.reduce((sum, t) => sum + t.rMultiple, 0);
  const avgR = total > 0 ? totalR / total : 0;
  const totalPnl = trades.reduce((sum, t) => sum + t.pnl, 0);
  const winningSum = trades.filter((t) => t.outcome === "win").reduce((s, t) => s + t.rMultiple, 0);
  const losingSum = Math.abs(trades.filter((t) => t.outcome === "loss").reduce((s, t) => s + t.rMultiple, 0));
  const profitFactor = losingSum > 0 ? winningSum / losingSum : winningSum > 0 ? Infinity : 0;
  const avgHold = total > 0 ? trades.reduce((s, t) => s + t.holdMinutes, 0) / total : 0;

  // Win rate over time (for sparkline) — 20 buckets
  const sorted = [...trades].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  const bucketSize = Math.max(1, Math.floor(sorted.length / 20));
  const sparklineBuckets: number[] = [];
  for (let i = 0; i < sorted.length; i += bucketSize) {
    const bucket = sorted.slice(i, i + bucketSize);
    const bucketWins = bucket.filter((t) => t.outcome === "win").length;
    sparklineBuckets.push(bucket.length > 0 ? bucketWins / bucket.length : 0);
  }

  // R:R distribution buckets
  const rrBuckets: { label: string; count: number; win: number; loss: number }[] = [
    { label: "≤ -3", count: 0, win: 0, loss: 0 },
    { label: "-3", count: 0, win: 0, loss: 0 },
    { label: "-2", count: 0, win: 0, loss: 0 },
    { label: "-1", count: 0, win: 0, loss: 0 },
    { label: "0", count: 0, win: 0, loss: 0 },
    { label: "+1", count: 0, win: 0, loss: 0 },
    { label: "+2", count: 0, win: 0, loss: 0 },
    { label: "+3", count: 0, win: 0, loss: 0 },
    { label: "≥ +4", count: 0, win: 0, loss: 0 },
  ];
  for (const t of trades) {
    const idx =
      t.rMultiple <= -3 ? 0 :
      t.rMultiple <= -2 ? 1 :
      t.rMultiple <= -1 ? 2 :
      t.rMultiple <= -0.2 ? 3 :
      t.rMultiple < 0.2 ? 4 :
      t.rMultiple < 1.5 ? 5 :
      t.rMultiple < 2.5 ? 6 :
      t.rMultiple < 3.5 ? 7 : 8;
    rrBuckets[idx].count++;
    if (t.outcome === "win") rrBuckets[idx].win++;
    else if (t.outcome === "loss") rrBuckets[idx].loss++;
  }
  const maxRR = Math.max(...rrBuckets.map((b) => b.count), 1);

  // Regime performance table
  const regimeMap = new Map<Regime, RegimeStats>();
  for (const t of trades) {
    let s = regimeMap.get(t.regime);
    if (!s) {
      s = { trades: 0, wins: 0, losses: 0, winRate: 0, avgR: 0, totalPnl: 0 };
      regimeMap.set(t.regime, s);
    }
    s.trades++;
    if (t.outcome === "win") s.wins++;
    else if (t.outcome === "loss") s.losses++;
    s.totalPnl += t.pnl;
    s.avgR += t.rMultiple;
  }
  for (const s of regimeMap.values()) {
    s.winRate = s.trades > 0 ? s.wins / s.trades : 0;
    s.avgR = s.trades > 0 ? s.avgR / s.trades : 0;
  }
  const regimeOrder: Regime[] = ["trend_up", "trend_down", "range", "volatile", "compression"];
  const regimeStats = regimeOrder.map((r) => ({
    regime: r,
    stats: regimeMap.get(r) ?? { trades: 0, wins: 0, losses: 0, winRate: 0, avgR: 0, totalPnl: 0 },
  }));
  const maxRegimeTrades = Math.max(...regimeStats.map((r) => r.stats.trades), 1);

  // Recent trades log (use the sorted desc array directly)

  return {
    total,
    wins,
    losses,
    winRate,
    avgR: Math.round(avgR * 100) / 100,
    profitFactor: profitFactor === Infinity ? Infinity : Math.round(profitFactor * 100) / 100,
    avgHold: Math.round(avgHold),
    totalPnl: Math.round(totalPnl * 100) / 100,
    sparkline: sparklineBuckets,
    rrBuckets,
    maxRR,
    regimeStats,
    maxRegimeTrades,
  };
}

/* ──────────────────────────────────────────────────────────────
   Helpers
   ────────────────────────────────────────────────────────────── */

function regimeLabel(r: Regime): string {
  return r === "trend_up" ? "Trend Up" : r === "trend_down" ? "Trend Down" : r === "volatile" ? "Volatile" : r === "compression" ? "Compression" : "Range";
}

function formatDate(ts: string): string {
  const d = new Date(ts);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/* ──────────────────────────────────────────────────────────────
   Sparkline SVG
   ────────────────────────────────────────────────────────────── */

function SparklineChart({ data, width = 200, height = 48 }: { data: number[]; width?: number; height?: number }) {
  if (data.length < 2) return null;
  const maxVal = Math.max(...data, 0.01);
  const minVal = Math.min(...data, 0);
  const range = maxVal - minVal || 1;
  const padding = 2;
  const chartWidth = width - padding * 2;
  const chartHeight = height - padding * 2;

  const points = data.map((val, i) => {
    const x = padding + (i / (data.length - 1)) * chartWidth;
    const y = padding + chartHeight - (val - minVal) / range * chartHeight;
    return `${x},${y}`;
  });

  // Gradient fill polygon
  const fillPoints = [
    `${padding},${padding + chartHeight}`,
    ...points,
    `${padding + chartWidth},${padding + chartHeight}`,
  ];

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="flex-shrink-0" aria-hidden="true">
      <defs>
        <linearGradient id="sparkline-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent-positive)" stopOpacity="0.25" />
          <stop offset="100%" stopColor="var(--accent-positive)" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <polygon points={fillPoints.join(" ")} fill="url(#sparkline-fill)" />
      <polyline points={points.join(" ")} fill="none" stroke="var(--accent-positive)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ──────────────────────────────────────────────────────────────
   Gauge SVG (profit factor)
   ────────────────────────────────────────────────────────────── */

function Gauge({ value, maxValue = 3, label }: { value: number; maxValue?: number; label: string }) {
  const displayValue = value === Infinity ? 3.5 : Math.min(value, maxValue);
  const fraction = displayValue / maxValue;
  const angle = 180 * fraction;
  const rad = (angle - 180) * (Math.PI / 180);
  const cx = 60;
  const cy = 60;
  const r = 48;
  const startX = cx - r;
  const startY = cy;
  const endX = cx + r * Math.cos(rad);
  const endY = cy + r * Math.sin(rad);
  const largeArc = fraction > 0.5 ? 1 : 0;
  const isInfinity = value === Infinity;

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={120} height={80} viewBox="0 0 120 80" aria-hidden="true">
        {/* Background arc */}
        <path
          d={`M ${startX} ${startY} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
          fill="none"
          stroke="var(--line-subtle)"
          strokeWidth="8"
          strokeLinecap="round"
        />
        {/* Value arc */}
        <path
          d={`M ${startX} ${startY} A ${r} ${r} 0 ${largeArc} 1 ${endX} ${endY}`}
          fill="none"
          stroke={isInfinity ? "var(--accent-positive)" : value < 1 ? "var(--accent-danger)" : value < 1.5 ? "var(--accent-warn)" : "var(--accent-positive)"}
          strokeWidth="8"
          strokeLinecap="round"
        />
        {/* Current value text */}
        <text x={cx} y={cy + 4} textAnchor="middle" fontSize="16" fontWeight="700" fill="var(--text-strong)" fontFamily="system-ui">
          {isInfinity ? "∞" : value.toFixed(2)}
        </text>
      </svg>
      <span className="text-[10px] font-medium uppercase tracking-[0.12em] text-[var(--text-label)]">{label}</span>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────
   Histogram bars
   ────────────────────────────────────────────────────────────── */

function RrHistogram({
  buckets,
  maxCount,
}: {
  buckets: { label: string; count: number; win: number; loss: number }[];
  maxCount: number;
}) {
  return (
    <div className="flex items-end gap-1.5 h-24">
      {buckets.map((bucket) => {
        const height = maxCount > 0 ? (bucket.count / maxCount) * 100 : 0;
        const winPortion = bucket.count > 0 ? bucket.win / bucket.count : 0;
        const winHeight = height * winPortion;
        const lossHeight = height * (1 - winPortion);
        return (
          <div key={bucket.label} className="flex flex-col items-center flex-1 min-w-0">
            <div className="w-full relative" style={{ height: `${height}%`, minHeight: bucket.count > 0 ? "2px" : "0" }}>
              {lossHeight > 0 && (
                <div
                  className="absolute bottom-0 w-full rounded-t-sm"
                  style={{ height: `${lossHeight}%`, background: "var(--accent-danger)" }}
                  title={`Losses: ${bucket.loss}`}
                />
              )}
              {winHeight > 0 && (
                <div
                  className="absolute bottom-0 w-full rounded-t-sm"
                  style={{ height: `${winHeight}%`, background: "var(--accent-positive)" }}
                  title={`Wins: ${bucket.win}`}
                />
              )}
            </div>
            <span className="text-[9px] font-medium text-[var(--text-muted)] mt-1 truncate w-full text-center">
              {bucket.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────
   Regime heatmap cell
   ────────────────────────────────────────────────────────────── */

function HeatmapCell({
  label,
  value,
  maxValue,
  format,
  goodWhen,
}: {
  label: string;
  value: number;
  maxValue: number;
  format: "pct" | "r" | "count";
  goodWhen: "high" | "low";
}) {
  const intensity = maxValue > 0 ? Math.min(value / maxValue, 1) : 0;
  const isGood =
    goodWhen === "high"
      ? value >= maxValue * 0.6
      : value <= maxValue * 0.4;
  const isNeutral = !isGood && intensity > 0.2;

  const bgHue = goodWhen === "high" ? 160 : 0;
  const bg = isGood
    ? `hsla(${bgHue}, 50%, ${45 - intensity * 20}%, ${0.15 + intensity * 0.25})`
    : isNeutral
      ? `hsla(40, 30%, 55%, ${0.1 + intensity * 0.15})`
      : `hsla(0, 50%, 55%, ${0.08 + intensity * 0.15})`;

  const textColor = isGood
    ? `hsla(${bgHue}, 40%, 70%, 1)`
    : isNeutral
      ? "var(--text-body)"
      : "var(--accent-danger)";

  const display =
    format === "pct"
      ? `${(value * 100).toFixed(0)}%`
      : format === "r"
        ? (value > 0 ? "+" : "") + value.toFixed(2)
        : String(value);

  return (
    <div
      className="flex flex-col items-center justify-center rounded-lg px-2 py-2 min-h-[3rem]"
      style={{ background: bg }}
    >
      <span className="text-xs font-semibold" style={{ color: textColor }}>
        {display}
      </span>
      <span className="text-[9px] text-[var(--text-muted)] mt-0.5 uppercase tracking-wider">
        {label}
      </span>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────
   Pipe icon for directional visualization
   ────────────────────────────────────────────────────────────── */

function DirectionArrow({ direction }: { direction: "buy" | "sell" }) {
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-xs font-semibold ${
        direction === "buy" ? "text-[var(--accent-positive)]" : "text-[var(--accent-danger)]"
      }`}
    >
      <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
        {direction === "buy" ? (
          <polygon points="5,0 10,8 0,8" />
        ) : (
          <polygon points="5,10 10,2 0,2" />
        )}
      </svg>
      {direction === "buy" ? "BUY" : "SELL"}
    </span>
  );
}

function OutcomeBadge({ outcome }: { outcome: "win" | "loss" | "breakeven" }) {
  if (outcome === "win") {
    return <span className="inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold bg-[var(--accent-positive-soft)] text-[var(--accent-positive)]">W</span>;
  }
  if (outcome === "loss") {
    return <span className="inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold bg-[var(--accent-danger-soft)] text-[var(--accent-danger)]">L</span>;
  }
  return <span className="inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold bg-[var(--accent-warn-soft)] text-[var(--accent-warn)]">B/E</span>;
}

/* ──────────────────────────────────────────────────────────────
   Main Dashboard Component
   ────────────────────────────────────────────────────────────── */

interface TradeJournalDashboardProps {
  /** External trade data — when empty/null, the dashboard shows an empty state. */
  externalTrades?: TradeRecord[] | null;
  /** Real confidence trend data from the intelligence engine */
  confidenceTrend?: ConfidenceTrend | null;
}

export function TradeJournalDashboard({ externalTrades, confidenceTrend }: TradeJournalDashboardProps) {
  const trades = useMemo(() => externalTrades ?? [], [externalTrades]);
  const stats = useMemo(() => computeStats(trades), [trades]);

  // Filters
  const [filterRegime, setFilterRegime] = useState<Regime | "all">("all");
  const [filterDirection, setFilterDirection] = useState<"all" | "buy" | "sell">("all");
  const [filterOutcome, setFilterOutcome] = useState<"all" | "win" | "loss" | "breakeven">("all");
  const [filterSearch, setFilterSearch] = useState("");

  const filteredTrades = useMemo(() => {
    return trades.filter((t) => {
      if (filterRegime !== "all" && t.regime !== filterRegime) return false;
      if (filterDirection !== "all" && t.direction !== filterDirection) return false;
      if (filterOutcome !== "all" && t.outcome !== filterOutcome) return false;
      if (filterSearch) {
        const q = filterSearch.toLowerCase();
        if (!t.symbol.toLowerCase().includes(q) && !t.id.toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [trades, filterRegime, filterDirection, filterOutcome, filterSearch]);

  // ── Empty state: no trade data available ────────────────
  if (trades.length === 0) {
    return (
      <div className="surface rounded-2xl p-8 text-center">
        <p className="text-sm font-medium text-[var(--text-body)]">
          No trade data available — run a live snapshot to populate.
        </p>
        <p className="text-xs text-[var(--text-muted)] mt-2">
          Trade outcomes, win rates, and R:R distribution will appear here after the first live analysis completes.
        </p>
      </div>
    );
  }

  const filterBtn = (label: string, active: boolean, onClick: () => void, key?: string) => (
    <button
      key={key}
      type="button"
      onClick={onClick}
      className={`tab-button ${active ? "tab-button--active" : ""}`}
      aria-pressed={active}
    >
      {label}
    </button>
  );

  return (
    <div className="space-y-5">
      {/* ── Header ──────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-[var(--text-strong)]">Trade Journal Dashboard</h3>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            {stats.total} trades analyzed &middot; Last 30 days
          </p>
        </div>
        <span
          className={`text-sm font-semibold tabular-nums ${
            stats.totalPnl > 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-danger)]"
          }`}
        >
          P&L: {stats.totalPnl > 0 ? "+" : ""}${stats.totalPnl.toLocaleString()}
        </span>
      </div>

      {/* ── KPI Stat Cards ──────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard title="Win Rate" value={`${(stats.winRate * 100).toFixed(0)}%`} subtitle={`${stats.wins}W / ${stats.losses}L`} accent="positive" />
        <StatCard title="Avg R:R" value={stats.avgR > 0 ? `+${stats.avgR.toFixed(2)}` : stats.avgR.toFixed(2)} subtitle={`${stats.total} trades`} accent={stats.avgR > 0 ? "positive" : "danger"} />
        <StatCard title="Profit Factor" value={stats.profitFactor === Infinity ? "∞" : stats.profitFactor.toFixed(2)} subtitle="Gross win / loss" accent={stats.profitFactor >= 1.5 ? "positive" : stats.profitFactor >= 1 ? "warn" : "danger"} />
        <StatCard title="Avg Hold" value={`${stats.avgHold}m`} subtitle="Per trade" accent="ink" />
      </div>

      {/* ── Confidence Trend Sparkline (from real engine data) ── */}
      {confidenceTrend && (
        <ConfidenceSparkline trend={confidenceTrend} />
      )}

      {/* ── Row: Sparkline + Gauge ───────────────────────────── */}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="surface rounded-2xl p-4">
          <p className="text-xs font-medium uppercase tracking-[0.15em] text-[var(--text-label)]">Win Rate Trend</p>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5">Rolling window &middot; {stats.sparkline.length} periods</p>
          <div className="mt-3 flex items-end justify-center">
            <SparklineChart data={stats.sparkline} width={260} height={56} />
          </div>
          <div className="mt-2 flex items-center justify-between text-[10px] text-[var(--text-muted)]">
            <span>{(stats.sparkline[0] * 100).toFixed(0)}%</span>
            <span>{(stats.sparkline[stats.sparkline.length - 1] * 100).toFixed(0)}%</span>
          </div>
        </div>
        <div className="surface rounded-2xl p-4 flex flex-col items-center justify-center">
          <Gauge value={stats.profitFactor} label="Profit Factor" />
        </div>
      </div>

      {/* ── R:R Distribution Histogram ──────────────────────── */}
      <div className="surface rounded-2xl p-4">
        <p className="text-xs font-medium uppercase tracking-[0.15em] text-[var(--text-label)]">R:R Distribution</p>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5">Green = wins &middot; Red = losses</p>
        <div className="mt-3">
          <RrHistogram buckets={stats.rrBuckets} maxCount={stats.maxRR} />
        </div>
        <div className="mt-2 flex justify-between text-[9px] text-[var(--text-muted)]">
          <span>Losses cluster</span>
          <span>Breakeven</span>
          <span>Wins cluster</span>
        </div>
      </div>

      {/* ── Regime-Performance Heatmap ───────────────────────── */}
      <div className="surface rounded-2xl p-4">
        <p className="text-xs font-medium uppercase tracking-[0.15em] text-[var(--text-label)]">Regime Performance</p>
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5">Heatmap &middot; darker = more trades</p>
        <div className="mt-3 grid grid-cols-4 gap-2">
          {/* Header row */}
          <div />
          {["Trades", "Win Rate", "Avg R", "P&L"].map((h) => (
            <div key={h} className="text-[9px] font-medium uppercase tracking-wider text-[var(--text-muted)] text-center pb-1">
              {h}
            </div>
          ))}
          {stats.regimeStats.map(({ regime, stats: s }) => (
            <React.Fragment key={regime}>
              <div className="text-xs font-medium text-[var(--text-body)] self-center">{regimeLabel(regime)}</div>
              <HeatmapCell label="" value={s.trades} maxValue={stats.maxRegimeTrades} format="count" goodWhen="high" />
              <HeatmapCell label="" value={s.winRate} maxValue={1} format="pct" goodWhen="high" />
              <HeatmapCell label="" value={s.avgR} maxValue={Math.max(...stats.regimeStats.map((r) => Math.abs(r.stats.avgR)), 0.01)} format="r" goodWhen="high" />
              <div className="flex items-center justify-center">
                <span
                  className={`text-xs font-semibold tabular-nums ${s.totalPnl > 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-danger)]"}`}
                >
                  {s.totalPnl > 0 ? "+" : ""}${s.totalPnl.toFixed(0)}
                </span>
              </div>
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* ── Trade Log ─────────────────────────────────────────── */}
      <div className="surface rounded-2xl p-4">
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs font-medium uppercase tracking-[0.15em] text-[var(--text-label)]">Trade Log</p>
          <span className="text-[10px] text-[var(--text-muted)]">{filteredTrades.length} trades</span>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2 mb-3">
          {/* Regime filter */}
          <div className="flex items-center gap-1 flex-wrap">
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider mr-1">Regime:</span>
            {(["all", ...REGIMES] as const).map((r) =>
              filterBtn(
                r === "all" ? "All" : regimeLabel(r as Regime),
                filterRegime === r,
                () => setFilterRegime(r as Regime | "all"),
                `regime-${r}`,
              )
            )}
          </div>
          <div className="w-px h-4 bg-[var(--line-subtle)]" />
          {/* Direction filter */}
          <div className="flex items-center gap-1 flex-wrap">
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider mr-1">Direction:</span>
            {(["all", "buy", "sell"] as const).map((d) =>
              filterBtn(d === "all" ? "All" : d.toUpperCase(), filterDirection === d, () => setFilterDirection(d), `dir-${d}`)
            )}
          </div>
          <div className="w-px h-4 bg-[var(--line-subtle)]" />
          {/* Outcome filter */}
          <div className="flex items-center gap-1 flex-wrap">
            <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider mr-1">Outcome:</span>
            {(["all", "win", "loss", "breakeven"] as const).map((o) =>
              filterBtn(
                o === "all" ? "All" : o === "breakeven" ? "B/E" : o.charAt(0).toUpperCase() + o.slice(1),
                filterOutcome === o,
                () => setFilterOutcome(o),
                `outcome-${o}`,
              )
            )}
          </div>
          <div className="ml-auto flex-1 max-w-[10rem]">
            <input
              type="text"
              placeholder="Search symbol or ID…"
              value={filterSearch}
              onChange={(e) => setFilterSearch(e.target.value)}
              className="w-full rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-strong)] px-2.5 py-1.5 text-xs text-[var(--text-strong)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--accent-ink)] transition-colors"
            />
          </div>
        </div>

        {/* Scrollable table */}
        <div className="overflow-x-auto -mx-4 px-4" style={{ maxHeight: "360px", overflowY: "auto" }}>
          <table className="w-full text-xs">
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-[var(--line-subtle)]">
                <Th>Time</Th>
                <Th>Symbol</Th>
                <Th>Dir</Th>
                <Th>Entry</Th>
                <Th>Exit</Th>
                <Th>R:R</Th>
                <Th>P&L</Th>
                <Th>Hold</Th>
                <Th>Outcome</Th>
                <Th>Regime</Th>
              </tr>
            </thead>
            <tbody>
              {filteredTrades.length === 0 ? (
                <tr>
                  <td colSpan={10} className="py-8 text-center text-[var(--text-muted)]">
                    No trades match the current filters.
                  </td>
                </tr>
              ) : (
                filteredTrades.slice(0, 100).map((trade) => (
                  <tr
                    key={trade.id}
                    className="border-b border-[var(--line-subtle)] hover:bg-[var(--bg-surface-hover)] transition-colors"
                  >
                    <Td>{formatDate(trade.timestamp)}</Td>
                    <Td>
                      <span className="font-medium">{trade.symbol === "R_75" ? "V75" : "V100"}</span>
                    </Td>
                    <Td>
                      <DirectionArrow direction={trade.direction} />
                    </Td>
                    <Td className="tabular-nums">{trade.entry.toFixed(1)}</Td>
                    <Td className="tabular-nums">{trade.exit.toFixed(1)}</Td>
                    <Td>
                      <span
                        className={`tabular-nums font-semibold ${
                          trade.outcome === "win"
                            ? "text-[var(--accent-positive)]"
                            : trade.outcome === "loss"
                              ? "text-[var(--accent-danger)]"
                              : "text-[var(--text-muted)]"
                        }`}
                      >
                        {trade.rMultiple > 0 ? "+" : ""}{trade.rMultiple.toFixed(1)}
                      </span>
                    </Td>
                    <Td>
                      <span
                        className={`tabular-nums font-semibold ${
                          trade.pnl > 0
                            ? "text-[var(--accent-positive)]"
                            : trade.pnl < 0
                              ? "text-[var(--accent-danger)]"
                              : "text-[var(--text-muted)]"
                        }`}
                      >
                        {trade.pnl > 0 ? "+" : ""}${trade.pnl.toFixed(0)}
                      </span>
                    </Td>
                    <Td className="tabular-nums">{trade.holdMinutes}m</Td>
                    <Td>
                      <OutcomeBadge outcome={trade.outcome} />
                    </Td>
                    <Td>
                      <span className="text-[10px] text-[var(--text-body)] capitalize">
                        {regimeLabel(trade.regime)}
                      </span>
                    </Td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────
   Small helpers
   ────────────────────────────────────────────────────────────── */

function StatCard({
  title,
  value,
  subtitle,
  accent,
}: {
  title: string;
  value: string;
  subtitle: string;
  accent: "positive" | "danger" | "warn" | "ink";
}) {
  const valueColor = {
    positive: "text-[var(--accent-positive)]",
    danger: "text-[var(--accent-danger)]",
    warn: "text-[var(--accent-warn)]",
    ink: "text-[var(--accent-ink)]",
  }[accent];

  return (
    <div className="info-card rounded-xl p-3.5 text-center">
      <p className="text-[10px] font-medium uppercase tracking-[0.15em] text-[var(--text-label)]">
        {title}
      </p>
      <p className={`mt-1.5 text-lg font-bold tabular-nums ${valueColor}`}>{value}</p>
      <p className="mt-0.5 text-[9px] text-[var(--text-muted)]">{subtitle}</p>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="text-left px-2 py-2 text-[10px] font-medium uppercase tracking-[0.12em] text-[var(--text-muted)] whitespace-nowrap bg-[var(--bg-panel)]">
      {children}
    </th>
  );
}

function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <td className={`px-2 py-2 text-[var(--text-body)] whitespace-nowrap ${className ?? ""}`}>
      {children}
    </td>
  );
}
