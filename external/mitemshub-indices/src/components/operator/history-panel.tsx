import React from "react";
import type { FreshCallResponse } from "../../lib/contracts";
import {
  formatCallHeadline,
  formatMarketCopy,
  formatTimestamp,
} from "../../lib/formatters";

type HistoryPanelProps = {
  history: FreshCallResponse[];
};

export function HistoryPanel({ history }: HistoryPanelProps) {
  return (
    <section className="rounded-[32px] border border-[rgba(15,23,42,0.08)] bg-[rgba(248,250,252,0.82)] px-6 py-7 shadow-[0_16px_32px_rgba(15,23,42,0.05)] md:px-8 md:py-8">
      <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
        Recent decisions
      </p>
      <h3 className="mt-3 text-2xl font-semibold text-[var(--text-strong,#0f172a)]">
        Recent trade plans
      </h3>
      <div className="mt-5 space-y-3">
        {history.length > 0 ? (
          history.map((entry) => (
            <article
              key={`${entry.symbol}-${entry.generated_at}`}
              className="rounded-[24px] border border-[rgba(15,23,42,0.08)] bg-white/78 p-4"
            >
              <div className="flex items-center justify-between gap-3">
                <p className="text-base font-medium text-[var(--text-strong,#0f172a)]">
                  {entry.symbol}
                </p>
                <p className="text-sm text-[rgba(15,23,42,0.52)]">
                  {formatTimestamp(entry.generated_at)}
                </p>
              </div>
              <p className="mt-2 text-sm font-medium text-[rgba(15,23,42,0.68)]">
                {formatCallHeadline(entry.call)}
              </p>
              <p className="mt-2 text-sm leading-6 text-[rgba(15,23,42,0.64)]">
                {formatMarketCopy(entry.why)}
              </p>
            </article>
          ))
        ) : (
          <div className="rounded-[24px] border border-[rgba(15,23,42,0.08)] bg-white/78 p-4">
            <p className="text-sm leading-6 text-[rgba(15,23,42,0.64)]">
              Recent live decisions appear here after you pull a fresh market read.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
