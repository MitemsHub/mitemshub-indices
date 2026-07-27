"use client"

import type { MarketThesis } from "../../lib/contracts";
import { formatPrice } from "../../lib/formatters";
import { SkeletonBar } from "../ui/skeleton";

type MarketThesisPanelProps = {
  thesis: MarketThesis | null;
  loading?: boolean;
};

function MarketThesisSkeleton() {
  return (
    <div className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4" aria-hidden="true">
      {/* Header: title + direction chip */}
      <div className="flex items-center justify-between">
        <SkeletonBar width="8rem" height="0.75rem" />
        <SkeletonBar width="3.5rem" height="1.5rem" className="rounded-full" />
      </div>

      {/* Thesis block */}
      <div className="mt-3 md:mt-4 p-3 md:p-4 rounded-lg bg-[var(--bg-panel-muted)] border border-[var(--line-subtle)]">
        <SkeletonBar width="4rem" height="0.625rem" className="mb-2" />
        <SkeletonBar width="100%" height="0.875rem" />
        <SkeletonBar width="85%" height="0.875rem" className="mt-1.5" />
        <SkeletonBar width="60%" height="0.875rem" className="mt-1.5" />
      </div>

      {/* 3 detail cards */}
      <div className="mt-3 md:mt-4 grid gap-2 md:gap-4 grid-cols-1 sm:grid-cols-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="info-card rounded-xl md:rounded-[1rem] p-3 md:p-4">
            <SkeletonBar width="5rem" height="0.625rem" />
            <SkeletonBar width="4rem" height="1rem" className="mt-2" />
            <SkeletonBar width="6rem" height="0.625rem" className="mt-1.5" />
          </div>
        ))}
      </div>

      {/* Timeframe alignment */}
      <div className="mt-3 md:mt-4">
        <SkeletonBar width="7rem" height="0.625rem" className="mb-2" />
        <SkeletonBar width="3rem" height="1.5rem" className="rounded-full" />
      </div>

      {/* Supporting evidence rows */}
      <div className="mt-3 md:mt-4">
        <SkeletonBar width="8rem" height="0.625rem" className="mb-2" />
        <div className="space-y-1.5 md:space-y-2">
          {[1, 2].map((i) => (
            <div key={i} className="flex items-start gap-2 md:gap-3 p-2 md:p-3 rounded-lg bg-[var(--accent-positive-soft)] border border-[var(--accent-positive-soft)]">
              <SkeletonBar width="1.25rem" height="1.25rem" className="rounded-full flex-shrink-0" />
              <div className="flex-1">
                <SkeletonBar width={`${4 + i}rem`} height="0.875rem" />
                <SkeletonBar width="8rem" height="0.625rem" className="mt-1.5" />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Counter evidence row */}
      <div className="mt-3 md:mt-4">
        <SkeletonBar width="7rem" height="0.625rem" className="mb-2" />
        <div className="p-2 md:p-3 rounded-lg bg-[var(--accent-danger-soft)] border border-[var(--accent-danger-soft)]">
          <div className="flex items-start gap-2 md:gap-3">
            <SkeletonBar width="1.25rem" height="1.25rem" className="rounded-full flex-shrink-0" />
            <div className="flex-1">
              <SkeletonBar width="5rem" height="0.875rem" />
              <SkeletonBar width="7rem" height="0.625rem" className="mt-1.5" />
            </div>
          </div>
        </div>
      </div>

      {/* Confidence bar */}
      <div className="mt-3 md:mt-4 p-3 md:p-4 rounded-lg bg-[var(--accent-ink-soft)] border border-[var(--accent-ink-soft)]">
        <SkeletonBar width="6rem" height="0.625rem" className="mb-2" />
        <SkeletonBar width="100%" height="0.875rem" />
      </div>
    </div>
  );
}

export function MarketThesisPanel({ thesis, loading }: MarketThesisPanelProps) {
  if (loading) {
    return <MarketThesisSkeleton />;
  }

  if (!thesis) {
    return (
      <div className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">Current Market Thesis</p>
        <p className="mt-4 text-sm text-[var(--text-body)]">Market thesis is not available for the current call state.</p>
      </div>
    );
  }

  const directionColors = {
    bullish: "text-[var(--accent-positive)] bg-[var(--accent-positive-soft)] border-[var(--accent-positive-soft)]",
    bearish: "text-[var(--accent-danger)] bg-[var(--accent-danger-soft)] border-[var(--accent-danger-soft)]",
    neutral: "text-[var(--text-muted)] bg-[var(--bg-panel-muted)] border-[var(--line-subtle)]",
  };

  return (
    <div className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
      <div className="flex items-center justify-between">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">Current Market Thesis</p>
        <span className={`info-chip rounded-full px-2 md:px-3 py-0.5 md:py-1 text-xs md:text-sm font-medium ${directionColors[thesis.direction] || directionColors.neutral}`}>
          {thesis.direction.toUpperCase()}
        </span>
      </div>

      <div className="mt-3 md:mt-4 p-3 md:p-4 rounded-lg bg-[var(--bg-panel-muted)] border border-[var(--line-subtle)]">
        <p className="text-[11px] md:text-sm font-medium text-[var(--text-strong)] mb-1">Thesis</p>
        <p className="text-sm md:text-base text-[var(--text-body)] leading-6 md:leading-7">{thesis.thesis}</p>
      </div>

      <div className="mt-3 md:mt-4 grid gap-2 md:gap-4 grid-cols-1 sm:grid-cols-3">
        <DetailCard title="Invalidation Price" value={thesis.invalidation_price ? formatPrice(thesis.invalidation_price) : "\u2014"} hint={thesis.invalidation_reason} />
        <DetailCard title="Primary Target" value={thesis.primary_target ? formatPrice(thesis.primary_target) : "\u2014"} hint="Primary profit objective" />
        <DetailCard title="Extended Target" value={thesis.extended_target ? formatPrice(thesis.extended_target) : "\u2014"} hint="Extended if momentum continues" />
      </div>

      <div className="mt-3 md:mt-4">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-[var(--text-muted)] mb-2">Timeframe Alignment</p>
        <span className={`info-chip rounded-full px-2 md:px-3 py-0.5 md:py-1 text-xs md:text-sm ${thesis.timeframe_alignment === "full" ? "text-[var(--accent-positive)] bg-[var(--accent-positive-soft)]" : thesis.timeframe_alignment === "partial" ? "text-[var(--accent-warn)] bg-[var(--accent-warn-soft)]" : "text-[var(--accent-danger)] bg-[var(--accent-danger-soft)]"}`}>
          {thesis.timeframe_alignment.charAt(0).toUpperCase() + thesis.timeframe_alignment.slice(1)}
        </span>
      </div>

      {thesis.key_evidence.length > 0 && (
        <div className="mt-3 md:mt-4">
          <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-gray-500 mb-2">Supporting Evidence</p>
          <div className="space-y-1.5 md:space-y-2">
            {thesis.key_evidence.map((ev, i) => (
              <div key={i} className="flex items-start gap-2 md:gap-3 p-2 md:p-3 rounded-lg bg-[var(--accent-positive-soft)] border border-[var(--accent-positive-soft)]">
                <span className="flex-shrink-0 w-4 h-4 md:w-5 md:h-5 rounded-full bg-[var(--accent-positive)] text-white text-[10px] md:text-xs flex items-center justify-center mt-0.5">✓</span>
                <div className="min-w-0">
                  <p className="text-xs md:text-sm font-medium text-[var(--text-strong)]">{ev.name}</p>
                  <p className="text-[10px] md:text-xs text-[var(--text-body)] mt-0.5">{ev.description}</p>
                  <p className="text-[10px] md:text-xs text-[var(--accent-positive)] mt-1">Strength: {(ev.strength * 100).toFixed(0)}% • {ev.source}</p>
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
              <div key={i} className="p-2 md:p-3 rounded-lg bg-[var(--accent-danger-soft)] border border-[var(--accent-danger-soft)]">
                <div className="flex items-start gap-2 md:gap-3">
                  <span className="flex-shrink-0 w-4 h-4 md:w-5 md:h-5 rounded-full bg-[var(--accent-danger)] text-white text-[10px] md:text-xs flex items-center justify-center mt-0.5">✗</span>
                  <div className="min-w-0">
                    <p className="text-xs md:text-sm font-medium text-[var(--text-strong)]">{ev.name}</p>
                    <p className="text-[10px] md:text-xs text-[var(--text-body)] mt-0.5">{ev.description}</p>
                    <p className="text-[10px] md:text-xs text-[var(--accent-danger)] mt-1">Strength: {(ev.strength * 100).toFixed(0)}% • {ev.source}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-3 md:mt-4 p-3 md:p-4 rounded-lg bg-[var(--accent-ink-soft)] border border-[var(--accent-ink-soft)]">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-[var(--accent-ink)] mb-2">Confidence: {(thesis.confidence * 100).toFixed(0)}%</p>
        <p className="text-xs md:text-sm text-[var(--text-body)]">Based on {thesis.key_evidence.length} supporting and {thesis.counter_evidence.length} counter factors</p>
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
