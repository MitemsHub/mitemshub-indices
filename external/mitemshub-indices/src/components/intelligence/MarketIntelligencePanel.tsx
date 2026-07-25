"use client"

import type { MarketIntelligence } from "../../lib/contracts";
import { formatNumber, formatPrice } from "../../lib/formatters";

/** Normalize various direction string formats to canonical "bullish" | "bearish" | "neutral". */
function normalizeDirection(dir: string | null | undefined): "bullish" | "bearish" | "neutral" {
  if (!dir) return "neutral";
  const lower = dir.toLowerCase().replace(/[^a-z\s]/g, "").trim();
  if (lower.startsWith("bull") || lower.startsWith("buy") || lower.startsWith("long")) return "bullish";
  if (lower.startsWith("bear") || lower.startsWith("sell") || lower.startsWith("short")) return "bearish";
  return "neutral";
}

type MarketIntelligencePanelProps = {
  intelligence: MarketIntelligence | null;
  currentPrice: number | null;
};

export function MarketIntelligencePanel({
  intelligence,
  currentPrice,
}: MarketIntelligencePanelProps) {
  if (!intelligence) {
    return (
      <div className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
        <p className="utility-copy text-xs uppercase tracking-[0.2em]">AI Market Intelligence</p>
        <p className="mt-4 text-sm text-[var(--text-body)]">Market intelligence is not available for the current call state.</p>
      </div>
    );
  }

  // ── Call vs Structure divergence
  const structureDir = normalizeDirection((intelligence as any).structure_direction);
  const callDir = normalizeDirection((intelligence as any).call_direction);
  const diverges = structureDir !== "neutral" && callDir !== "neutral" && structureDir !== callDir;
  const hasDirection = structureDir !== "neutral" || callDir !== "neutral";

  const regimeColors: Record<string, string> = {
    trend_up: "text-[var(--accent-positive)] bg-[var(--accent-positive-soft)] border-[var(--accent-positive-soft)]",
    trend_down: "text-[var(--accent-danger)] bg-[var(--accent-danger-soft)] border-[var(--accent-danger-soft)]",
    range: "text-[var(--accent-ink)] bg-[var(--accent-ink-soft)] border-[var(--accent-ink-soft)]",
    volatile: "text-[var(--accent-volatile)] bg-[var(--accent-volatile-soft)] border-[var(--accent-volatile-soft)]",
    compression: "text-[var(--accent-warn)] bg-[var(--accent-warn-soft)] border-[var(--accent-warn-soft)]",
  };

  return (
    <div className="intelligence-panel surface rounded-[1.5rem]">
      {/* Top accent bar */}
      <div
        className="h-[3px] w-full rounded-t-[1.5rem] transition-colors duration-500"
        style={{
          backgroundColor: diverges
            ? "var(--accent-warn)"
            : hasDirection
            ? "var(--accent-positive)"
            : "transparent",
        }}
      />

      <div className="p-3 md:p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">AI Market Intelligence</p>
          {diverges && (
            <span
              className="inline-flex items-center gap-1 rounded-full px-1.5 md:px-2 py-0.5 text-[9px] md:text-[10px] font-semibold uppercase tracking-[0.08em] whitespace-nowrap"
              style={{
                backgroundColor: "var(--accent-warn-soft)",
                color: "var(--accent-warn)",
                border: "1px solid color-mix(in srgb, var(--accent-warn) 25%, transparent)",
              }}
              title={`Structure says ${structureDir} but the engine decided ${callDir}`}
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M12 9v4" />
                <path d="M12 17h.01" />
              </svg>
              Divergence
            </span>
          )}
        </div>
        <span className={`info-chip rounded-full px-2 md:px-3 py-0.5 md:py-1 text-xs md:text-sm flex-shrink-0 ${regimeColors[intelligence.regime] || "text-[var(--accent-neutral)] bg-[var(--accent-neutral-soft)]"}`}>
          {intelligence.regime.replace("_", " ")}
        </span>
      </div>

      {/* Metric cards — 2 cols on mobile, 2 on md, 4 on lg */}
      <div className="mt-3 md:mt-4 grid grid-cols-2 gap-2 md:gap-3 lg:gap-4">
        <MetricCard
          label="Current Price"
          value={formatPrice(currentPrice || intelligence.current_price)}
          subtitle={intelligence.symbol}
        />
        <MetricCard
          label="Structure Bias"
          value={formatNumber(intelligence.structure_bias, 2)}
          subtitle={
            (intelligence as any).structure_direction === "bullish"
              ? "Bullish (multi-TF)"
              : (intelligence as any).structure_direction === "bearish"
              ? "Bearish (multi-TF)"
              : intelligence.structure_bias > 0.3
              ? "Bullish Structure"
              : intelligence.structure_bias < -0.3
              ? "Bearish Structure"
              : "Neutral"
          }
          trend={
            (intelligence as any).structure_direction === "bullish"
              ? "bullish"
              : (intelligence as any).structure_direction === "bearish"
              ? "bearish"
              : intelligence.structure_bias > 0.3
              ? "bullish"
              : intelligence.structure_bias < -0.3
              ? "bearish"
              : "neutral"
          }
        />
        <MetricCard
          label="Trend"
          value={(intelligence.trend_direction || "neutral").replace(/\s*\(.*\)\s*$/, "")}
          subtitle={
            (intelligence as any).call_direction
              ? `Call: ${(intelligence as any).call_direction}`
              : intelligence.trend_direction
          }
          trend={
            (intelligence.trend_direction || "").toLowerCase().startsWith("bullish")
              ? "bullish"
              : (intelligence.trend_direction || "").toLowerCase().startsWith("bearish")
              ? "bearish"
              : "neutral"
          }
        />
        <MetricCard
          label="Volatility"
          value={
            intelligence.atr_ratio > 1.5
              ? "High"
              : intelligence.atr_ratio < 0.7
              ? "Low"
              : "Normal"
          }
          subtitle={`${formatNumber(intelligence.atr_ratio, 2)} ATR`}
          trend={
            intelligence.atr_ratio > 1.5
              ? "bearish"
              : intelligence.atr_ratio < 0.7
              ? "bullish"
              : "neutral"
          }
        />
      </div>

      {/* Detail cards — stack on mobile, 2 on md, 3 on lg */}
      <div className="mt-3 md:mt-4 grid gap-2 md:gap-3 lg:grid-cols-3 md:grid-cols-2">
        <DetailCard
          title="Advanced Metrics"
          items={[
            { label: "Hurst", value: formatNumber(intelligence.hurst_exponent, 3), hint: intelligence.hurst_exponent > 0.6 ? "Persistent" : intelligence.hurst_exponent < 0.4 ? "Mean reverting" : "Random" },
            { label: "Entropy", value: formatNumber(intelligence.entropy, 3), hint: intelligence.entropy > 0.7 ? "High uncertainty" : intelligence.entropy < 0.3 ? "Low" : "Moderate" },
            { label: "Displacement", value: formatNumber(intelligence.displacement_atr, 2), hint: intelligence.displacement_atr > 1.5 ? "Strong" : intelligence.displacement_atr < 0.5 ? "Weak" : "Moderate" },
          ]}
        />
        <DetailCard
          title="Key Levels"
          items={[
            { label: "Swing High", value: formatPrice(intelligence.key_levels.recent_swing_high) },
            { label: "Swing Low", value: formatPrice(intelligence.key_levels.recent_swing_low) },
            { label: "Invalidation", value: intelligence.key_levels.thesis_invalidation != null && intelligence.key_levels.thesis_invalidation !== 0 ? formatPrice(intelligence.key_levels.thesis_invalidation) : "\u2014" },
            { label: "Target", value: intelligence.key_levels.primary_target != null && intelligence.key_levels.primary_target !== 0 ? formatPrice(intelligence.key_levels.primary_target) : "\u2014" },
            { label: "Extended", value: intelligence.key_levels.extended_target != null && intelligence.key_levels.extended_target !== 0 ? formatPrice(intelligence.key_levels.extended_target) : "\u2014" },
          ]}
        />
        <DetailCard
          title="Volatility Profile"
          items={[
            { label: "ATR Ratio", value: formatNumber(intelligence.atr_ratio, 2), hint: intelligence.atr_ratio > 1.5 ? "Expanded" : intelligence.atr_ratio < 0.7 ? "Contracted" : "Normal" },
            { label: "Regime", value: intelligence.volatility_state },
            { label: "Price", value: formatPrice(currentPrice || intelligence.current_price) },
          ]}
        />
      </div>
    </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  subtitle,
  trend,
}: {
  label: string;
  value: string;
  subtitle?: string;
  trend?: "bullish" | "bearish" | "neutral";
}) {
  const trendColors = {
    bullish: "text-[var(--accent-positive)]",
    bearish: "text-[var(--accent-danger)]",
    neutral: "text-[var(--accent-neutral)]",
  };
  const trendIcons = {
    bullish: "\u25b2",
    bearish: "\u25bc",
    neutral: "\u25a0",
  };

  return (
    <div className="info-card rounded-xl md:rounded-[1.5rem] p-3 md:p-4 lg:p-5">
      <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">{label}</p>
      <p className="mt-1.5 md:mt-2 text-base md:text-lg font-semibold text-[var(--text-strong)] leading-tight">{value}</p>
      {subtitle && <p className="mt-0.5 md:mt-1 text-[11px] md:text-sm leading-5 text-[var(--text-body)]">{subtitle}</p>}
      {trend && (
        <p className="mt-0.5 md:mt-1 flex items-center gap-1 text-[11px] md:text-sm">
          <span className={trendColors[trend]}>{trendIcons[trend]}</span>
          <span className={trendColors[trend]}>{trend}</span>
        </p>
      )}
    </div>
  );
}

function DetailCard({
  title,
  items,
}: {
  title: string;
  items: Array<{ label: string; value: string; hint?: string }>;
}) {
  return (
    <div className="info-card rounded-xl md:rounded-[1.5rem] p-3 md:p-4 lg:p-5">
      <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-[var(--text-label)]">{title}</p>
      <dl className="mt-2 md:mt-4 space-y-2 md:space-y-3">
        {items.map((item, i) => (
          <div key={i} className="flex flex-col gap-0.5">
            <dt className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.1em] text-[var(--text-muted)]">{item.label}</dt>
            <dd className="text-sm md:text-base font-medium text-[var(--text-strong)]">{item.value}</dd>
            {item.hint && <dd className="text-[10px] md:text-xs text-[var(--text-muted)]">{item.hint}</dd>}
          </div>
        ))}
      </dl>
    </div>
  );
}
