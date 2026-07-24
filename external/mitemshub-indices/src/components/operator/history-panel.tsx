import React from "react";
import type { FreshCallResponse } from "../../lib/contracts";
import {
  formatCallHeadline,
  formatGuardianState,
  formatMarketCopy,
  formatSymbol,
  formatTimestamp,
} from "../../lib/formatters";

type HistoryPanelProps = {
  history: FreshCallResponse[];
};

function HistoryEntry({ entry }: { entry: FreshCallResponse }) {
  const isStandAside = entry.call === "stand_aside";
  const isBuy = entry.call === "buy_candidate";
  return (
    <article className="rounded-xl border border-[var(--line-subtle)] bg-[var(--bg-panel-strong)] p-4 transition hover:shadow-[0_8px_24px_rgba(22,29,45,0.04)]">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            className={`pulse-dot ${
              isStandAside ? "pulse-dot--muted" :
              isBuy ? "pulse-dot--positive" :
              "pulse-dot--danger"
            }`}
            aria-hidden="true"
          />
          <p className="text-sm font-medium text-[var(--text-strong)]">{formatSymbol(entry.symbol)}</p>
        </div>
        <p className="text-xs text-[var(--text-muted)]">{formatTimestamp(entry.generated_at)}</p>
      </div>
      <p className="mt-1.5 text-sm font-medium text-[var(--text-body)]">
        {formatCallHeadline(entry.call)}
      </p>
      {entry.trade_status !== "not_valid" && (
        <span className={`status-badge mt-2 ${
          entry.guardian_state === "confirmed" ? "status-badge--confirmed" :
          entry.guardian_state === "actionable" ? "status-badge--actionable" :
          entry.guardian_state === "failing" ? "status-badge--failing" :
          entry.guardian_state === "cancelled" ? "status-badge--cancelled" :
          "status-badge--forming"
        }`}>
          {formatGuardianState(entry.guardian_state)}
        </span>
      )}
      <p className="mt-2 text-xs leading-5 text-[var(--text-muted)]">
        {formatMarketCopy(entry.why)}
      </p>
    </article>
  );
}

export function HistoryPanel({ history }: HistoryPanelProps) {
  return (
    <section className="rounded-2xl border border-[var(--line-subtle)] bg-[rgba(248,250,252,0.82)] px-5 py-5 shadow-[var(--shadow-card)]">
      <p className="utility-copy text-[11px] uppercase tracking-[0.24em] text-[var(--text-label)]">
        Recent decisions
      </p>
      <h3 className="display-serif mt-2 text-lg font-semibold text-[var(--text-strong)]">
        Recent trade plans
      </h3>

      <div className="mt-4 space-y-3">
        {history.length > 0 ? (
          history.map((entry, index) => (
            <HistoryEntry key={`${index}-${entry.symbol}-${entry.generated_at}`} entry={entry} />
          ))
        ) : (
          <div className="rounded-xl border border-[var(--line-subtle)] bg-white/78 p-5 text-center">
            <div className="pulse-dot pulse-dot--muted mx-auto mb-2" aria-hidden="true" />
            <p className="text-sm leading-6 text-[var(--text-muted)]">
              Recent live decisions appear here after you pull a fresh market read.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
