"use client"

import type { ConfidenceBreakdown } from "../../lib/contracts";
import { formatPct } from "../../lib/formatters";
import { SkeletonBar, SkeletonCard } from "../ui/skeleton";

type ConfidenceBreakdownPanelProps = {
  breakdown: ConfidenceBreakdown | null;
  modelProbability?: number | null;
  loading?: boolean;
};

function ConfidenceBreakdownSkeleton() {
  return (
    <div className="intelligence-panel surface rounded-[1.5rem] p-4" aria-hidden="true">
      <p className="utility-copy text-xs uppercase tracking-[0.2em]">Confidence Breakdown</p>
      {/* Header chips skeleton */}
      <div className="flex items-center justify-end gap-3 mt-3">
        <SkeletonBar width="5rem" height="1.5rem" className="rounded-full" />
        <SkeletonBar width="4rem" height="1.5rem" className="rounded-full" />
      </div>
      {/* Component rows skeleton — 8 rows matching real layout */}
      <div className="mt-3 md:mt-4 space-y-2 md:space-y-3">
        {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
          <div key={i} className="info-card rounded-[1rem] p-3 md:p-4">
            <div className="flex items-center justify-between">
              <div className="flex-1 min-w-0">
                <SkeletonBar width={`${3 + (i % 3)}rem`} height="0.875rem" />
                <SkeletonBar width="6rem" height="0.625rem" className="mt-1.5" />
              </div>
              {/* Desktop bar skeleton */}
              <div className="hidden md:flex items-center gap-4">
                <SkeletonBar width="8rem" height="0.5rem" className="rounded-full" />
                <div className="text-right w-24">
                  <SkeletonBar width="3rem" height="0.875rem" className="ml-auto" />
                  <SkeletonBar width="2.5rem" height="0.625rem" className="mt-1 ml-auto" />
                </div>
              </div>
              {/* Mobile bar skeleton */}
              <div className="md:hidden w-36 flex-shrink-0">
                <SkeletonBar width="100%" height="1.25rem" className="rounded-full" />
                <SkeletonBar width="2rem" height="0.5rem" className="mt-1 ml-auto" />
              </div>
            </div>
            <SkeletonBar width="7rem" height="0.625rem" className="mt-2" />
          </div>
        ))}
      </div>
      {/* Weights section skeleton */}
      <div className="mt-4 pt-4 border-t border-[var(--line-subtle)]">
        <SkeletonBar width="6rem" height="0.625rem" />
        <div className="mt-3 flex flex-wrap gap-2">
          {[1, 2, 3, 4, 5].map((i) => (
            <SkeletonBar key={i} width={`${2 + (i % 3)}rem`} height="1.25rem" className="rounded-full" />
          ))}
        </div>
      </div>
    </div>
  );
}

export function ConfidenceBreakdownPanel({
  breakdown,
  modelProbability,
  loading,
}: ConfidenceBreakdownPanelProps) {
  if (loading) {
    return <ConfidenceBreakdownSkeleton />;
  }

  if (!breakdown) {
    return (
      <div className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">Confidence Breakdown</p>
        <p className="mt-4 text-sm md:text-base text-[var(--text-body)]">Run a live read to load confidence breakdown.</p>
      </div>
    );
  }

  const weights = breakdown.weights || {
    model: 0.28,
    structure: 0.22,
    regime: 0.15,
    mean_reversion: 0.08,
    displacement: 0.07,
    momentum: 0.07,
    volatility: 0.05,
    confluence: 0.08,
  };

  const components = [
    { key: "model", label: "Model Probability", value: breakdown.model, weight: weights.model, description: "Calibrated model probability" },
    { key: "structure", label: "Market Structure", value: breakdown.structure, weight: weights.structure, description: "BOS, FVG, sweeps, displacement" },
    { key: "regime", label: "Regime Alignment", value: breakdown.regime, weight: weights.regime, description: "Trend/range/volatile regime fit" },
    { key: "mean_reversion", label: "Mean Reversion", value: breakdown.mean_reversion, weight: weights.mean_reversion, description: "Position in range, RSI, channels" },
    { key: "displacement", label: "Displacement", value: breakdown.displacement, weight: weights.displacement, description: "ATR-normalized momentum" },
    { key: "momentum", label: "Momentum", value: breakdown.momentum, weight: weights.momentum, description: "Slope, EMA spread, returns" },
    { key: "volatility", label: "Volatility", value: breakdown.volatility, weight: weights.volatility, description: "ATR ratio, clustering, regime" },
    { key: "confluence", label: "Multi-TF Confluence", value: breakdown.confluence, weight: weights.confluence, description: "Multi-timeframe alignment" },
  ];

  return (
    <div className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
      <div className="flex items-center justify-between">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">Confidence Breakdown</p>
        <div className="flex items-center gap-2 md:gap-3 flex-wrap justify-end">
          <span className="info-chip rounded-full px-2 md:px-3 py-0.5 md:py-1 text-xs md:text-sm">
            Final: {formatPct(breakdown.final || breakdown.calibrated)}
          </span>
          {modelProbability !== undefined && (
            <span className="info-chip rounded-full px-2 md:px-3 py-0.5 md:py-1 text-xs md:text-sm text-gray-600 bg-gray-50">
              Model: {formatPct(modelProbability)}
            </span>
          )}
          {breakdown.calibrated && breakdown.calibrated !== breakdown.final && (
            <span className="info-chip rounded-full px-2 md:px-3 py-0.5 md:py-1 text-xs md:text-sm text-blue-600 bg-blue-50">
              Calibrated: {formatPct(breakdown.calibrated)}
            </span>
          )}
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {components.map((comp, i) => (
          <ConfidenceComponentRow
            key={i}
            label={comp.label}
            value={comp.value}
            weight={comp.weight}
            description={comp.description}
          />
        ))}
      </div>

      <div className="mt-3 md:mt-4 pt-3 md:pt-4 border-t border-[var(--line-subtle)]">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-[var(--text-muted)]">Component Weights</p>
        <div className="mt-2 md:mt-3 flex flex-wrap gap-1.5 md:gap-2">
          {Object.entries(weights).map(([key, weight]) => (
            <span key={key} className="info-chip rounded-full px-2 py-1 text-xs">
              {key}: {formatPct(weight)}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function ConfidenceComponentRow({
  label,
  value,
  weight,
  description,
}: {
  label: string;
  value: number;
  weight: number;
  description: string;
}) {
  const contribution = value * weight * 100;
  const barPercent = Math.min(value * 100, 100);
  const showLabelInside = barPercent > 25;

  return (
    <div className="info-card rounded-lg md:rounded-[1rem] p-2.5 md:p-4">
      <div className="flex items-center justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-xs md:text-sm font-medium text-gray-900">{label}</p>
          <p className="mt-0.5 text-[10px] md:text-xs text-gray-500">{description}</p>
        </div>
        {/* Desktop: bar + label outside (original layout) */}
        <div className="hidden md:flex items-center gap-4">
          <div className="w-32 h-2 bg-gray-100 rounded-full overflow-hidden flex-shrink-0">
            <div
              className="h-full bg-gradient-to-r from-blue-500 to-indigo-600 rounded-full transition-[width] duration-300"
              style={{ width: `${barPercent}%` }}
            />
          </div>
          <div className="text-right w-24">
            <p className="text-sm font-semibold text-gray-900">{value.toFixed(2)}</p>
            <p className="text-xs text-gray-500">Weight: {(weight * 100).toFixed(0)}%</p>
          </div>
        </div>
        {/* Mobile: taller bar with percentage label inside */}
        <div className="md:hidden w-36 flex-shrink-0">
          <div className="relative h-5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-blue-500 to-indigo-600 rounded-full transition-[width] duration-300"
              style={{ width: `${barPercent}%` }}
            />
            {showLabelInside && (
              <span className="absolute inset-0 flex items-center justify-end pr-2 text-[0.625rem] font-bold text-white tabular-nums drop-shadow-sm">
                {(value * 100).toFixed(0)}%
              </span>
            )}
          </div>
          {!showLabelInside && (
            <p className="mt-1 text-right text-[0.625rem] font-semibold text-gray-600 tabular-nums">
              {(value * 100).toFixed(0)}%
            </p>
          )}
          <p className="mt-0.5 text-right text-[0.5625rem] text-gray-400">
            w: {(weight * 100).toFixed(0)}%
          </p>
        </div>
      </div>
      <div className="mt-2 text-xs text-gray-500">
        Contribution to final: {contribution.toFixed(2)}%
      </div>
    </div>
  );
}