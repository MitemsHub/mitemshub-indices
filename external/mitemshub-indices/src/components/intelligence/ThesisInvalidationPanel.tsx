"use client"

import type { ThesisInvalidation } from "../../lib/contracts";
import { formatPrice, formatNumber, formatPct } from "../../lib/formatters";

type ThesisInvalidationPanelProps = {
  invalidation: ThesisInvalidation | null;
  currentPrice?: number | null;
};

export function ThesisInvalidationPanel({ invalidation, currentPrice }: ThesisInvalidationPanelProps) {
  if (!invalidation) {
    return (
      <section className="intelligence-panel surface rounded-[1.5rem] p-4">
        <p className="utility-copy text-xs uppercase tracking-[0.2em]">Thesis Invalidation</p>
        <p className="mt-4 text-base text-[var(--text-body)]">Run a live read to load invalidation analysis.</p>
      </section>
    );
  }

  const invalidationPrice = invalidation.level;
  const distance = invalidation.distance_from_current;
  const distancePct = currentPrice && invalidationPrice ? (Math.abs(currentPrice - invalidationPrice) / currentPrice * 100) : 0;
  const isLong = currentPrice && invalidationPrice && currentPrice > invalidationPrice;
  const direction = isLong ? "below" : "above";

  return (
    <section className="intelligence-panel surface rounded-[1.5rem] p-4">
      <div className="flex items-center justify-between">
        <p className="utility-copy text-xs uppercase tracking-[0.2em]">Thesis Invalidation</p>
        <span className="info-chip rounded-full px-3 py-1 text-sm font-medium text-red-700 bg-red-50">
          ⚠ Invalidation Level
        </span>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <DetailCard
          title="Invalidation Price"
          value={formatPrice(invalidationPrice)}
          hint={`Thesis invalid if price moves ${direction}`}
        />
        <DetailCard
          title="Current Price"
          value={currentPrice ? formatPrice(currentPrice) : "—"}
          hint={currentPrice ? `Live: ${formatPrice(currentPrice)}` : "—"}
        />
        <DetailCard
          title="Distance to Invalidation"
          value={`${formatPrice(distance)} (${formatPct(distancePct / 100)})`}
          hint={distancePct < 1 ? "CRITICALLY CLOSE" : distancePct < 2 ? "APPROACHING" : "Safe distance"}
        />
      </div>

      <div className="mt-4 p-4 rounded-lg bg-red-50 border border-red-200">
        <div className="flex items-start gap-3">
          <span className="flex-shrink-0 w-8 h-8 rounded-full bg-red-500 text-white text-base flex items-center justify-center">⚠</span>
          <div>
            <p className="text-sm font-medium text-red-900">Invalidation Reason</p>
            <p className="mt-1 text-sm text-red-700">{invalidation.reason}</p>
          </div>
        </div>
      </div>

      <div className="mt-4">
        <p className="utility-copy text-xs uppercase tracking-[0.2em] text-gray-500 mb-3">Invalidation Triggers</p>
        <div className="space-y-2">
          {invalidation.invalidation_triggers.map((trigger, i) => (
            <div key={i} className="flex items-center gap-3 p-3 rounded-lg bg-red-50 border border-red-200">
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-red-500 text-white text-xs flex items-center justify-center">!</span>
              <p className="text-sm text-red-800">{trigger}</p>
            </div>
          ))}
        </div>
      </div>

      {invalidation.time_since_signal && (
        <div className="mt-4 p-3 rounded-lg bg-amber-50 border border-amber-200">
          <p className="utility-copy text-xs uppercase tracking-[0.2em] text-amber-700 mb-1">Time Since Signal</p>
          <p className="text-sm text-amber-900">{formatNumber(invalidation.time_since_signal)} seconds ago</p>
        </div>
      )}
    </section>
  );
}

function DetailCard({ title, value, hint }: { title: string; value: string; hint?: string }) {
  return (
    <div className="info-card rounded-[1rem] p-4">
      <p className="utility-copy text-xs uppercase tracking-[0.2em] text-gray-500">{title}</p>
      <p className="mt-2 text-base font-semibold text-gray-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}