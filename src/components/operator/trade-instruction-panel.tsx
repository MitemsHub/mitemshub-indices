import React from "react";
import type { FreshCallResponse } from "../../lib/contracts";
import {
  formatActionSummary,
  formatMarketCopy,
  formatPrice,
} from "../../lib/formatters";

type TradeInstructionPanelProps = {
  call: FreshCallResponse | null;
};

export function TradeInstructionPanel({ call }: TradeInstructionPanelProps) {
  const actionSummary = call ? formatActionSummary(call) : null;
  const hasExecutionLevels =
    call?.entry !== null &&
    call?.entry !== undefined &&
    call?.stop_loss !== null &&
    call?.stop_loss !== undefined &&
    call?.take_profit !== null &&
    call?.take_profit !== undefined;

  return (
    <section className="surface rounded-[32px] px-6 py-7 md:px-8 md:py-8">
      <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
        Trade execution
      </p>
      <h3 className="mt-3 text-2xl font-semibold text-[var(--text-strong,#0f172a)]">
        What to do now
      </h3>
      {call ? (
        <div className="mt-5 space-y-5 text-sm text-[rgba(15,23,42,0.72)]">
          <p className="max-w-2xl leading-7 text-[var(--text-body)]">
            {formatMarketCopy(call.decision_summary ?? call.why)}
          </p>
          {hasExecutionLevels ? (
            <dl className="grid gap-3 md:grid-cols-3">
              <div className="info-card rounded-[24px] p-4">
                <dt className="utility-copy text-[11px] uppercase tracking-[0.24em]">
                  Entry
                </dt>
                <dd className="mt-3 text-lg font-semibold text-[var(--text-strong,#0f172a)]">
                  {formatPrice(call.entry)}
                </dd>
              </div>
              <div className="info-card rounded-[24px] p-4">
                <dt className="utility-copy text-[11px] uppercase tracking-[0.24em]">
                  Stop
                </dt>
                <dd className="mt-3 text-lg font-semibold text-[var(--text-strong,#0f172a)]">
                  {formatPrice(call.stop_loss)}
                </dd>
              </div>
              <div className="info-card rounded-[24px] p-4">
                <dt className="utility-copy text-[11px] uppercase tracking-[0.24em]">
                  Target
                </dt>
                <dd className="mt-3 text-lg font-semibold text-[var(--text-strong,#0f172a)]">
                  {formatPrice(call.take_profit)}
                </dd>
              </div>
            </dl>
          ) : (
            <div className="info-card rounded-[24px] p-4">
              <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
                Execution levels
              </p>
              <p className="mt-3 text-sm leading-7 text-[var(--text-body)]">
                Entry, stop, and target appear only when a trade is ready.
              </p>
            </div>
          )}
          <div className="action-card rounded-[24px] px-4 py-4">
            <p className="utility-copy text-[11px] uppercase tracking-[0.24em]">
              Action
            </p>
            <p className="mt-3 text-sm leading-7 text-[var(--text-strong)]">
              {actionSummary}
            </p>
          </div>
        </div>
      ) : (
        <p className="mt-5 text-base leading-7 text-[var(--text-body)]">
          The action steps appear after a live reading has been pulled.
        </p>
      )}
    </section>
  );
}
