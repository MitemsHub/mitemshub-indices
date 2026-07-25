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
    <section className="surface rounded-2xl px-4 py-4 md:px-5 md:py-5">
      <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
        System check
      </p>
      <h3 className="mt-3 text-xl font-semibold text-[var(--text-strong)]">
        Bridge and market feed
      </h3>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div className="info-card rounded-[24px] p-4">
          <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
            Bridge status
          </p>
          <p className="mt-3 text-base font-semibold text-[var(--text-strong)]">
            {formatLabel(status.backend_status)}
          </p>
        </div>
        <div className="info-card rounded-[24px] p-4">
          <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
            Reconnect events
          </p>
          <p className="mt-3 text-base font-semibold text-[var(--text-strong)]">
            {status.transport_event_count}
          </p>
        </div>
      </div>
       {status.transport_event_count > 0 && (
         <p className="mt-4 text-sm leading-6 text-[var(--text-body)]">
           Latest reconnect note: {formatLabel(status.latest_transport_event)}.{" "}
           {status.latest_transport_reason}
         </p>
       )}
    </section>
  );
}
