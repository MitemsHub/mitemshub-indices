import React from "react";
import { formatLabel } from "../../lib/formatters";

type ReviewSystemPanelProps = {
  status: {
    latest_call: string;
    alert_count: number;
    suppressed_context_count: number;
    transport_event_count: number;
    latest_transport_event: string;
    latest_transport_reason: string;
    backend_status: string;
    journal_status: string;
  };
};

export function ReviewSystemPanel({ status }: ReviewSystemPanelProps) {
  return (
    <section className="rounded-[32px] border border-[rgba(15,23,42,0.08)] bg-[rgba(248,250,252,0.88)] px-6 py-7 shadow-[0_16px_32px_rgba(15,23,42,0.05)] md:px-8 md:py-8">
      <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
        System check
      </p>
      <h3 className="mt-3 text-2xl font-semibold text-[var(--text-strong,#0f172a)]">
        Bridge and market feed
      </h3>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <div className="rounded-[24px] border border-[rgba(15,23,42,0.08)] bg-white/80 p-4">
          <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
            Bridge status
          </p>
          <p className="mt-3 text-base font-semibold text-[var(--text-strong,#0f172a)]">
            {formatLabel(status.backend_status)}
          </p>
        </div>
        <div className="rounded-[24px] border border-[rgba(15,23,42,0.08)] bg-white/80 p-4">
          <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
            Reconnect events
          </p>
          <p className="mt-3 text-base font-semibold text-[var(--text-strong,#0f172a)]">
            {status.transport_event_count}
          </p>
        </div>
      </div>
      <p className="mt-4 text-sm leading-6 text-[rgba(15,23,42,0.68)]">
        Latest reconnect note: {formatLabel(status.latest_transport_event)}.{" "}
        {status.latest_transport_reason}
      </p>
    </section>
  );
}
