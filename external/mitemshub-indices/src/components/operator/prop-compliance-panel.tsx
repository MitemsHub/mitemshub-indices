import React from "react";
import type { FreshCallResponse } from "../../lib/contracts";
import type { PropAccountState } from "../../lib/prop-policy";
import {
  formatLabel,
  formatPercent,
  formatPrice,
  formatPropProfile,
} from "../../lib/formatters";

type PropCompliancePanelProps = {
  call: FreshCallResponse | null;
  profile: PropAccountState;
};

export function PropCompliancePanel({
  call,
  profile,
}: PropCompliancePanelProps) {
  const noTradeActive =
    call?.call === "stand_aside" || call?.trade_status !== "valid";

  return (
    <section className="rounded-2xl border border-[var(--accent-warn-soft)] bg-[var(--accent-warn-soft)] px-5 py-5 shadow-[0_18px_40px_rgba(154,106,24,0.06)]">
      <p className="text-[11px] uppercase tracking-[0.24em] text-[var(--accent-warn)]">
        Prop protection
      </p>
      <h3 className="display-serif mt-2 text-lg font-semibold text-[var(--text-strong)]">
        Compliance status
      </h3>
      <p className="mt-3 text-sm text-[var(--text-body)]">
        {formatPropProfile(profile.profile)}
      </p>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-[var(--accent-warn-soft)] bg-[var(--bg-panel-strong)] p-4">
          <p className="text-[10px] uppercase tracking-[0.2em] text-[var(--accent-warn)]">
            Policy state
          </p>
          <p className="mt-2 text-sm font-semibold text-[var(--text-strong)]">
            {call ? formatLabel(call.prop_compliance) : "Monitoring"}
          </p>
        </div>
        <div className="rounded-xl border border-[var(--accent-warn-soft)] bg-[var(--bg-panel-strong)] p-4">
          <p className="text-[10px] uppercase tracking-[0.2em] text-[var(--accent-warn)]">
            Allowed risk
          </p>
          <p className="mt-2 text-sm font-semibold text-[var(--text-strong)]">
            {noTradeActive ? "No trade active" : formatPercent(call?.prop_adjusted_risk ?? null)}
          </p>
        </div>
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-[var(--accent-warn-soft)] bg-[var(--bg-panel-strong)] p-4">
          <p className="text-[10px] uppercase tracking-[0.2em] text-[var(--accent-warn)]">
            Daily loss room left
          </p>
          <p className="mt-2 text-sm font-semibold text-[var(--text-strong)]">
            {formatPrice(call?.prop_remaining_daily_buffer ?? null)}
          </p>
        </div>
        <div className="rounded-xl border border-[var(--accent-warn-soft)] bg-[var(--bg-panel-strong)] p-4">
          <p className="text-[10px] uppercase tracking-[0.2em] text-[var(--accent-warn)]">
            Total drawdown room left
          </p>
          <p className="mt-2 text-sm font-semibold text-[var(--text-strong)]">
            {formatPrice(call?.prop_remaining_overall_buffer ?? null)}
          </p>
        </div>
      </div>

      <p className="mt-4 text-xs leading-5 text-[var(--text-body)]">
        Daily loss room left is how much of today&apos;s 5% loss limit remains.
        Total drawdown room left is how much equity remains before the overall
        10% drawdown limit is breached.
      </p>

      {call?.prop_block_reason ? (
        <p className="mt-3 text-xs leading-5 text-[var(--text-body)]">
          {call.prop_block_reason}
        </p>
      ) : null}
    </section>
  );
}
