"use client"

import type { MarketThesis } from "../../lib/contracts";
import { formatPrice } from "../../lib/formatters";

type MarketThesisPanelProps = {
  thesis: MarketThesis | null;
};

export function MarketThesisPanel({ thesis }: MarketThesisPanelProps) {
  if (!thesis) {
    return (
      <div className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">Current Market Thesis</p>
        <p className="mt-4 text-sm text-[var(--text-body)]">Market thesis is not available for the current call state.</p>
      </div>
    );
  }

  const directionColors = {
    bullish: "text-green-700 bg-green-50 border-green-200",
    bearish: "text-red-700 bg-red-50 border-red-200",
    neutral: "text-gray-700 bg-gray-50 border-gray-200",
  };

  return (
    <div className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
      <div className="flex items-center justify-between">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">Current Market Thesis</p>
        <span className={`info-chip rounded-full px-2 md:px-3 py-0.5 md:py-1 text-xs md:text-sm font-medium ${directionColors[thesis.direction] || directionColors.neutral}`}>
          {thesis.direction.toUpperCase()}
        </span>
      </div>

      <div className="mt-3 md:mt-4 p-3 md:p-4 rounded-lg bg-white/50 border border-gray-100">
        <p className="text-[11px] md:text-sm font-medium text-gray-900 mb-1">Thesis</p>
        <p className="text-sm md:text-base text-gray-700 leading-6 md:leading-7">{thesis.thesis}</p>
      </div>

      <div className="mt-3 md:mt-4 grid gap-2 md:gap-4 grid-cols-1 sm:grid-cols-3">
        <DetailCard title="Invalidation Price" value={thesis.invalidation_price ? formatPrice(thesis.invalidation_price) : "\u2014"} hint={thesis.invalidation_reason} />
        <DetailCard title="Primary Target" value={thesis.primary_target ? formatPrice(thesis.primary_target) : "\u2014"} hint="Primary profit objective" />
        <DetailCard title="Extended Target" value={thesis.extended_target ? formatPrice(thesis.extended_target) : "\u2014"} hint="Extended if momentum continues" />
      </div>

      <div className="mt-3 md:mt-4">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-gray-500 mb-2">Timeframe Alignment</p>
        <span className={`info-chip rounded-full px-2 md:px-3 py-0.5 md:py-1 text-xs md:text-sm ${thesis.timeframe_alignment === "full" ? "text-green-700 bg-green-50" : thesis.timeframe_alignment === "partial" ? "text-amber-700 bg-amber-50" : "text-red-700 bg-red-50"}`}>
          {thesis.timeframe_alignment.charAt(0).toUpperCase() + thesis.timeframe_alignment.slice(1)}
        </span>
      </div>

      {thesis.key_evidence.length > 0 && (
        <div className="mt-3 md:mt-4">
          <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-gray-500 mb-2">Supporting Evidence</p>
          <div className="space-y-1.5 md:space-y-2">
            {thesis.key_evidence.map((ev, i) => (
              <div key={i} className="flex items-start gap-2 md:gap-3 p-2 md:p-3 rounded-lg bg-green-50 border border-green-200">
                <span className="flex-shrink-0 w-4 h-4 md:w-5 md:h-5 rounded-full bg-green-500 text-white text-[10px] md:text-xs flex items-center justify-center mt-0.5">✓</span>
                <div className="min-w-0">
                  <p className="text-xs md:text-sm font-medium text-green-900">{ev.name}</p>
                  <p className="text-[10px] md:text-xs text-green-700 mt-0.5">{ev.description}</p>
                  <p className="text-[10px] md:text-xs text-green-600 mt-1">Strength: {(ev.strength * 100).toFixed(0)}% • {ev.source}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {thesis.counter_evidence.length > 0 && (
        <div className="mt-3 md:mt-4">
          <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-gray-500 mb-2">Counter Evidence</p>
          <div className="space-y-1.5 md:space-y-2">
            {thesis.counter_evidence.map((ev, i) => (
              <div key={i} className="p-2 md:p-3 rounded-lg bg-red-50 border border-red-200">
                <div className="flex items-start gap-2 md:gap-3">
                  <span className="flex-shrink-0 w-4 h-4 md:w-5 md:h-5 rounded-full bg-red-500 text-white text-[10px] md:text-xs flex items-center justify-center mt-0.5">✗</span>
                  <div className="min-w-0">
                    <p className="text-xs md:text-sm font-medium text-red-900">{ev.name}</p>
                    <p className="text-[10px] md:text-xs text-red-700 mt-0.5">{ev.description}</p>
                    <p className="text-[10px] md:text-xs text-red-600 mt-1">Strength: {(ev.strength * 100).toFixed(0)}% • {ev.source}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-3 md:mt-4 p-3 md:p-4 rounded-lg bg-blue-50 border border-blue-200">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-blue-700 mb-2">Confidence: {(thesis.confidence * 100).toFixed(0)}%</p>
        <p className="text-xs md:text-sm text-blue-800">Based on {thesis.key_evidence.length} supporting and {thesis.counter_evidence.length} counter factors</p>
      </div>
    </div>
  );
}

function DetailCard({ title, value, hint }: { title: string; value: string; hint?: string | null }) {
  return (
    <div className="info-card rounded-xl md:rounded-[1rem] p-3 md:p-4">
      <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-[var(--text-muted)]">{title}</p>
      <p className="mt-1.5 md:mt-2 text-sm md:text-base font-semibold text-[var(--text-strong)]">{value}</p>
      {hint && <p className="mt-0.5 md:mt-1 text-[10px] md:text-xs text-[var(--text-muted)]">{hint}</p>}
    </div>
  );
}
