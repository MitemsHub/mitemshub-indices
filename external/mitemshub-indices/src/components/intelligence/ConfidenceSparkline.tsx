"use client";

import type { ConfidenceTrend } from "../../lib/contracts";

type ConfidenceSparklineProps = {
  trend: ConfidenceTrend | null;
};

const TREND_COLORS: Record<string, { stroke: string; fill: string; label: string }> = {
  improving: { stroke: "var(--accent-positive)", fill: "var(--accent-positive)", label: "Improving" },
  stable: { stroke: "var(--accent-ink)", fill: "var(--accent-ink)", label: "Stable" },
  degrading: { stroke: "var(--accent-danger)", fill: "var(--accent-danger)", label: "Degrading" },
};

export function ConfidenceSparkline({ trend }: ConfidenceSparklineProps) {
  if (!trend || trend.history.length < 2) {
    return (
      <div className="surface rounded-2xl p-4">
        <p className="text-xs font-medium uppercase tracking-[0.15em] text-[var(--text-label)]">
          Confidence Trend
        </p>
        <p className="mt-4 text-xs text-[var(--text-muted)]">
          Run live reads to build confidence history.
        </p>
      </div>
    );
  }

  const colors = TREND_COLORS[trend.trend] ?? TREND_COLORS.stable;
  const points = trend.history.slice(0, 20).reverse(); // most recent first, flip to chronological (oldest left)
  const n = points.length;
  const maxVal = Math.max(...points.map((p) => p.confidence), 0.01);
  const minVal = Math.min(...points.map((p) => p.confidence), 0);
  const range = maxVal - minVal || 0.5;
  const latest = points[n - 1];

  const W = 280;
  const H = 72;
  const PAD = 2;
  const CW = W - PAD * 2;
  const CH = H - PAD * 2;

  const toX = (i: number) => PAD + (i / Math.max(n - 1, 1)) * CW;
  const toY = (v: number) => PAD + CH - ((v - minVal) / range) * CH;

  const linePoints = points.map((p, i) => `${toX(i)},${toY(p.confidence)}`);
  const fillPoints = [
    `${toX(0)},${PAD + CH}`,
    ...linePoints,
    `${toX(n - 1)},${PAD + CH}`,
  ];

  const midIdx = Math.floor(n / 2);

  return (
    <div className="surface rounded-2xl p-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.15em] text-[var(--text-label)]">
            Confidence Trend
          </p>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
            Last {n} reads &middot; Volatility {(trend.volatility * 100).toFixed(0)}%
          </p>
        </div>
        <span
          className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold"
          style={{
            background: `${colors.fill}14`,
            color: colors.stroke,
            border: `1px solid ${colors.fill}28`,
          }}
        >
          <span
            className="inline-block w-1.5 h-1.5 rounded-full"
            style={{ background: colors.stroke }}
          />
          {colors.label}
        </span>
      </div>

      {/* Mini stat row */}
      <div className="mt-3 grid grid-cols-3 gap-2">
        <CompactStat label="Current" value={`${(latest.confidence * 100).toFixed(0)}%`} color={colors.stroke} />
        <CompactStat label="High" value={`${(maxVal * 100).toFixed(0)}%`} color={colors.stroke} />
        <CompactStat label="Low" value={`${(minVal * 100).toFixed(0)}%`} color={colors.stroke} />
      </div>

      {/* SVG sparkline */}
      <div className="mt-3">
        <svg
          width="100%"
          height={H}
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          aria-hidden="true"
          className="block"
        >
          <defs>
            <linearGradient id="cs-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={colors.fill} stopOpacity="0.25" />
              <stop offset="100%" stopColor={colors.fill} stopOpacity="0.02" />
            </linearGradient>
          </defs>
          {/* Fill area */}
          <polygon points={fillPoints.join(" ")} fill="url(#cs-fill)" />
          {/* Line */}
          <polyline
            points={linePoints.join(" ")}
            fill="none"
            stroke={colors.stroke}
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {/* End dot */}
          <circle cx={toX(n - 1)} cy={toY(latest.confidence)} r="3" fill={colors.stroke} stroke="var(--bg-panel-strong)" strokeWidth="1.5" />
        </svg>
      </div>

      {/* Bottom timescale */}
      <div className="mt-1 flex items-center justify-between text-[9px] text-[var(--text-muted)]">
        <span>{formatTime(points[0].timestamp)}</span>
        <span>{formatTime(points[midIdx].timestamp)}</span>
        <span>{formatTime(latest.timestamp)}</span>
      </div>

      {/* Regime/direction tags row */}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {points.filter((_, i) => i === 0 || i === n - 1 || i === midIdx).map((p, i) => (
          <span
            key={i}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[9px] font-medium"
            style={{
              background: `${colors.fill}0c`,
              color: "var(--text-muted)",
            }}
          >
            {p.regime?.replace("_", " ") ?? "—"}
            {p.direction_bias ? ` · ${p.direction_bias}` : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

function CompactStat({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: string;
}) {
  return (
    <div className="text-center">
      <p className="text-[9px] font-medium uppercase tracking-[0.12em] text-[var(--text-muted)]">
        {label}
      </p>
      <p className="mt-0.5 text-sm font-bold tabular-nums" style={{ color }}>
        {value}
      </p>
    </div>
  );
}

function formatTime(ts: string): string {
  const d = new Date(ts);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
