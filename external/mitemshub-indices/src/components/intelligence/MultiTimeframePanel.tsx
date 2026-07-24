"use client"

import type { MarketIntelligence, TimeframeAnalysis } from "../../lib/contracts";
import { SkeletonBar, SkeletonRow, SkeletonCard } from "../ui/skeleton";

type MultiTimeframePanelProps = {
  multiTimeframe?: TimeframeAnalysis[];
  marketIntelligence: MarketIntelligence | null;
  loading?: boolean;
};

const MTF_SKELETON_COLUMNS = [
  { width: "3rem" },
  { width: "4.5rem" },
  { width: "6rem", hide: "md" as const },
  { width: "5rem", hide: "lg" as const },
  { width: "3rem", hide: "lg" as const },
  { width: "5rem", hide: "md" as const },
  { width: "5rem" },
  { width: "4rem" },
];

function MultiTimeframeSkeleton() {
  return (
    <section className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4" aria-hidden="true">
      <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">Multi-Timeframe Alignment</p>
      {/* Desktop table skeleton */}
      <div className="hidden md:block mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)]">
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Timeframe</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Regime</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Structure Bias</th>
              <th className="hidden lg:table-cell text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">BOS / Sweeps</th>
              <th className="hidden lg:table-cell text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">FVG</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Displacement</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Direction</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Confidence</th>
            </tr>
          </thead>
          <tbody>
            <SkeletonRow columns={MTF_SKELETON_COLUMNS} />
            <SkeletonRow columns={MTF_SKELETON_COLUMNS} />
            <SkeletonRow columns={MTF_SKELETON_COLUMNS} />
          </tbody>
        </table>
      </div>
      {/* Mobile card skeleton */}
      <div className="md:hidden mt-3 space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="info-card rounded-xl p-3">
            <div className="flex items-center justify-between">
              <SkeletonBar width="3rem" height="0.875rem" />
              <SkeletonBar width="4rem" height="1.25rem" className="rounded-full" />
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <SkeletonBar width="100%" height="0.625rem" />
              <SkeletonBar width="100%" height="0.625rem" />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 md:mt-4">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-gray-500 mb-2 md:mb-3">Alignment Summary</p>
        <div className="grid gap-2 md:gap-3 grid-cols-1 md:grid-cols-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </div>
    </section>
  );
}

export function MultiTimeframePanel({ multiTimeframe, marketIntelligence, loading }: MultiTimeframePanelProps) {
  if (loading) {
    return <MultiTimeframeSkeleton />;
  }

  const timeframes = multiTimeframe || marketIntelligence?.multi_timeframe || [];

  if (!timeframes.length) {
    return (
      <section className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">Multi-Timeframe Alignment</p>
        <p className="mt-4 text-sm text-[var(--text-body)]">Multi-timeframe analysis is not available for the current call state.</p>
      </section>
    );
  }

  const regimeColors: Record<string, string> = {
    trend_up: "text-green-600 bg-green-50 border-green-200",
    trend_down: "text-red-600 bg-red-50 border-red-200",
    range: "text-blue-600 bg-blue-50 border-blue-200",
    volatile: "text-purple-600 bg-purple-50 border-purple-200",
    compression: "text-amber-600 bg-amber-50 border-amber-200",
    unknown: "text-gray-500 bg-gray-50 border-gray-200",
  };

  return (
    <section className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
      <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">Multi-Timeframe Alignment</p>

      {/* ── Desktop table (md+) ─────────────────────────────────── */}
      <div className="hidden md:block mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)]">
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Timeframe</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Regime</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Structure Bias</th>
              <th className="hidden lg:table-cell text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">BOS / Sweeps</th>
              <th className="hidden lg:table-cell text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">FVG</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Displacement</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Direction</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {timeframes.map((tf) => (
              <tr key={tf.timeframe} className="border-b border-[var(--border)]/50">
                <td className="py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em] font-mono">{tf.timeframe}</td>
                <td className="py-2 px-3">
                  <span className={`info-chip rounded-full px-2 py-0.5 text-xs ${regimeColors[tf.regime] || regimeColors.unknown}`}>
                    {tf.regime.replace("_", " ")}
                  </span>
                </td>
                <td className="py-2 px-3">
                  <div className="flex items-center gap-2">
                    <div className="w-20 h-2 bg-[var(--border)] rounded-full overflow-hidden">
                      <div className="h-full bg-blue-500" style={{ width: `${Math.abs(tf.structure_bias) * 100}%` }} />
                    </div>
                    <span className={tf.structure_bias > 0.3 ? "text-green-600" : tf.structure_bias < -0.3 ? "text-red-600" : "text-gray-600"}>
                      {tf.structure_bias > 0 ? "▲" : tf.structure_bias < 0 ? "▼" : "■"} {tf.structure_bias.toFixed(2)}
                    </span>
                  </div>
                </td>
                <td className="hidden lg:table-cell py-2 px-3 text-sm">
                  <div className="flex gap-1 text-xs">
                    {tf.bos_up > 0 && <span className="px-1.5 py-0.5 rounded bg-green-100 text-green-700">BOS↑</span>}
                    {tf.bos_down > 0 && <span className="px-1.5 py-0.5 rounded bg-red-100 text-red-700">BOS↓</span>}
                    {tf.liquidity_sweep_up > 0 && <span className="px-1.5 py-0.5 rounded bg-yellow-100 text-yellow-800">Sweep↑</span>}
                    {tf.liquidity_sweep_down > 0 && <span className="px-1.5 py-0.5 rounded bg-green-100 text-green-800">Sweep↓</span>}
                    {!(tf.bos_up > 0) && !(tf.bos_down > 0) && !(tf.liquidity_sweep_up > 0) && !(tf.liquidity_sweep_down > 0) && <span className="text-gray-400">—</span>}
                  </div>
                </td>
                <td className="hidden lg:table-cell py-2 px-3 text-sm">
                  <div className="flex gap-1 text-xs">
                    {tf.fvg_bullish_active > 0 && <span className="px-1.5 py-0.5 rounded bg-green-100 text-green-700">FVG↑</span>}
                    {tf.fvg_bearish_active > 0 && <span className="px-1.5 py-0.5 rounded bg-red-100 text-red-700">FVG↓</span>}
                    {!(tf.fvg_bullish_active > 0) && !(tf.fvg_bearish_active > 0) && <span className="text-gray-400">—</span>}
                  </div>
                </td>
                <td className="py-2 px-3">
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full bg-blue-500" style={{ width: `${Math.min(Math.abs(tf.displacement_atr) / 3, 1) * 100}%` }} />
                    </div>
                    <span className="text-sm font-mono font-medium">{tf.displacement_atr.toFixed(1)}</span>
                  </div>
                </td>
                <td className="py-2 px-3">
                  <span className={tf.direction_bias === "bullish" ? "text-green-600" : tf.direction_bias === "bearish" ? "text-red-600" : "text-gray-500"}>
                    {tf.direction_bias === "bullish" ? "▲ Bullish" : tf.direction_bias === "bearish" ? "▼ Bearish" : "■ Neutral"}
                  </span>
                </td>
                <td className="py-2 px-3">
                  <div className="w-20 h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div className="h-full bg-blue-500" style={{ width: `${tf.confidence * 100}%` }} />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Mobile card layout (< md) ───────────────────────────── */}
      <div className="md:hidden mt-3 space-y-2">
        {timeframes.map((tf) => (
          <div key={tf.timeframe} className="info-card rounded-xl p-3">
            {/* Header row: timeframe + regime chip + direction */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-bold uppercase text-[var(--text-strong)]">{tf.timeframe}</span>
                <span className={`info-chip rounded-full px-1.5 py-0.5 text-[10px] ${regimeColors[tf.regime] || regimeColors.unknown}`}>
                  {tf.regime.replace("_", " ")}
                </span>
              </div>
              <span className={`text-xs font-medium ${tf.direction_bias === "bullish" ? "text-green-600" : tf.direction_bias === "bearish" ? "text-red-600" : "text-gray-500"}`}>
                {tf.direction_bias === "bullish" ? "▲ Bullish" : tf.direction_bias === "bearish" ? "▼ Bearish" : "■ Neutral"}
              </span>
            </div>

            {/* Structure bias bar */}
            <div className="mt-2 flex items-center gap-2">
              <span className="text-[10px] text-[var(--text-muted)] w-16 flex-shrink-0">Structure</span>
              <div className="flex-1 h-2 bg-[var(--border)] rounded-full overflow-hidden">
                <div className="h-full bg-blue-500" style={{ width: `${Math.abs(tf.structure_bias) * 100}%` }} />
              </div>
              <span className={`text-[10px] font-mono font-medium w-8 text-right ${tf.structure_bias > 0.3 ? "text-green-600" : tf.structure_bias < -0.3 ? "text-red-600" : "text-gray-500"}`}>
                {tf.structure_bias.toFixed(2)}
              </span>
            </div>

            {/* Displacement bar */}
            <div className="mt-1.5 flex items-center gap-2">
              <span className="text-[10px] text-[var(--text-muted)] w-16 flex-shrink-0">Displacement</span>
              <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                <div className="h-full bg-blue-500" style={{ width: `${Math.min(Math.abs(tf.displacement_atr) / 3, 1) * 100}%` }} />
              </div>
              <span className="text-[10px] font-mono font-medium w-8 text-right">{tf.displacement_atr.toFixed(1)}</span>
            </div>

            {/* Confidence bar */}
            <div className="mt-1.5 flex items-center gap-2">
              <span className="text-[10px] text-[var(--text-muted)] w-16 flex-shrink-0">Confidence</span>
              <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                <div className="h-full bg-blue-500" style={{ width: `${tf.confidence * 100}%` }} />
              </div>
              <span className="text-[10px] font-mono font-medium w-8 text-right">{(tf.confidence * 100).toFixed(0)}%</span>
            </div>

            {/* BOS/FVG/Sweep chips — only show if any exist */}
            {(tf.bos_up > 0 || tf.bos_down > 0 || tf.liquidity_sweep_up > 0 || tf.liquidity_sweep_down > 0 || tf.fvg_bullish_active > 0 || tf.fvg_bearish_active > 0) && (
              <div className="mt-2 flex flex-wrap gap-1">
                {tf.bos_up > 0 && <span className="px-1.5 py-0.5 rounded text-[9px] bg-green-100 text-green-700">BOS↑</span>}
                {tf.bos_down > 0 && <span className="px-1.5 py-0.5 rounded text-[9px] bg-red-100 text-red-700">BOS↓</span>}
                {tf.liquidity_sweep_up > 0 && <span className="px-1.5 py-0.5 rounded text-[9px] bg-yellow-100 text-yellow-800">Sweep↑</span>}
                {tf.liquidity_sweep_down > 0 && <span className="px-1.5 py-0.5 rounded text-[9px] bg-green-100 text-green-800">Sweep↓</span>}
                {tf.fvg_bullish_active > 0 && <span className="px-1.5 py-0.5 rounded text-[9px] bg-green-100 text-green-700">FVG↑</span>}
                {tf.fvg_bearish_active > 0 && <span className="px-1.5 py-0.5 rounded text-[9px] bg-red-100 text-red-700">FVG↓</span>}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* ── Alignment Summary ───────────────────────────────────── */}
      <div className="mt-3 md:mt-4">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-gray-500 mb-2 md:mb-3">Alignment Summary</p>
        <div className="grid gap-2 md:gap-3 grid-cols-1 md:grid-cols-3">
          <AlignmentMetric label="Bias Alignment" value={calculateBiasAlignment(timeframes)} hint="How aligned are the timeframes?" />
          <AlignmentMetric label="Regime Consistency" value={calculateRegimeConsistency(timeframes)} hint="Do regimes agree across timeframes?" />
          <AlignmentMetric label="Structure Coherence" value={calculateStructureCoherence(timeframes)} hint="Do structures tell the same story?" />
        </div>
      </div>
    </section>
  );
}

function calculateBiasAlignment(timeframes: TimeframeAnalysis[]): string {
  if (!timeframes.length) return "—";
  const biases = timeframes.map((t) => t.structure_bias);
  const positive = biases.filter((b) => b > 0.1).length;
  const negative = biases.filter((b) => b < -0.1).length;
  if (positive === timeframes.length) return "Full Bullish";
  if (negative === timeframes.length) return "Full Bearish";
  if (positive > negative) return `Partial Bullish (${positive}/${timeframes.length})`;
  if (negative > positive) return `Partial Bearish (${negative}/${timeframes.length})`;
  return "Mixed";
}

function calculateRegimeConsistency(timeframes: TimeframeAnalysis[]): string {
  if (!timeframes.length) return "—";
  const regimes = timeframes.map((t) => t.regime);
  const unique = new Set(regimes);
  if (unique.size === 1) return `Full: ${Array.from(unique)[0].replace("_", " ")}`;
  return `Mixed (${unique.size} regimes)`;
}

function calculateStructureCoherence(timeframes: TimeframeAnalysis[]): string {
  if (!timeframes.length) return "—";
  const hasBOS = timeframes.some((t) => t.bos_up || t.bos_down);
  const hasFVG = timeframes.some((t) => t.fvg_bullish_active || t.fvg_bearish_active);
  const hasSweep = timeframes.some((t) => t.liquidity_sweep_up || t.liquidity_sweep_down);
  const signals = [hasBOS, hasFVG, hasSweep].filter(Boolean).length;
  return `${signals}/3 structure signals`;
}

function AlignmentMetric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="p-3 md:p-4 rounded-lg bg-gray-50 border border-gray-200">
      <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-gray-500 mb-1">{label}</p>
      <p className="text-sm md:text-base font-semibold text-gray-900">{value}</p>
      <p className="text-[10px] md:text-xs text-gray-500 mt-1">{hint}</p>
    </div>
  );
}
