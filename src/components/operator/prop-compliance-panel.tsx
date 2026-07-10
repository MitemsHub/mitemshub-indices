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
    <section className="rounded-[32px] border border-[rgba(154,106,24,0.22)] bg-[rgba(255,248,232,0.92)] px-6 py-7 shadow-[0_18px_40px_rgba(154,106,24,0.08)] md:px-8 md:py-8">
      <p className="text-[11px] uppercase tracking-[0.24em] text-[rgba(120,53,15,0.72)]">
        Prop protection
      </p>
      <h3 className="mt-3 text-3xl font-semibold text-[var(--text-strong,#0f172a)]">
        Compliance status
      </h3>
      <p className="mt-4 text-sm text-[rgba(15,23,42,0.72)]">
        {formatPropProfile(profile.profile)}
      </p>
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <div className="rounded-[24px] border border-[rgba(154,106,24,0.16)] bg-[rgba(255,255,255,0.72)] p-4">
          <p className="text-[11px] uppercase tracking-[0.24em] text-[rgba(120,53,15,0.72)]">
            Policy state
          </p>
          <p className="mt-3 text-lg font-semibold text-[var(--text-strong,#0f172a)]">
            {call ? formatLabel(call.prop_compliance) : "Monitoring"}
          </p>
        </div>
        <div className="rounded-[24px] border border-[rgba(154,106,24,0.16)] bg-[rgba(255,255,255,0.72)] p-4">
          <p className="text-[11px] uppercase tracking-[0.24em] text-[rgba(120,53,15,0.72)]">
            Allowed risk
          </p>
          <p className="mt-3 text-lg font-semibold text-[var(--text-strong,#0f172a)]">
            {noTradeActive ? "No trade active" : formatPercent(call?.prop_adjusted_risk ?? null)}
          </p>
        </div>
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div className="rounded-[24px] border border-[rgba(154,106,24,0.16)] bg-[rgba(255,255,255,0.72)] p-4">
          <p className="text-[11px] uppercase tracking-[0.24em] text-[rgba(120,53,15,0.72)]">
            Daily loss room left
          </p>
          <p className="mt-3 text-lg font-semibold text-[var(--text-strong,#0f172a)]">
            {formatPrice(call?.prop_remaining_daily_buffer ?? null)}
          </p>
        </div>
        <div className="rounded-[24px] border border-[rgba(154,106,24,0.16)] bg-[rgba(255,255,255,0.72)] p-4">
          <p className="text-[11px] uppercase tracking-[0.24em] text-[rgba(120,53,15,0.72)]">
            Total drawdown room left
          </p>
          <p className="mt-3 text-lg font-semibold text-[var(--text-strong,#0f172a)]">
            {formatPrice(call?.prop_remaining_overall_buffer ?? null)}
          </p>
        </div>
      </div>
      <p className="mt-4 text-sm leading-6 text-[rgba(15,23,42,0.68)]">
        Daily loss room left is how much of today&apos;s 5% loss limit remains.
        Total drawdown room left is how much equity remains before the overall
        10% drawdown limit is breached.
      </p>
      {call?.prop_block_reason ? (
        <p className="mt-4 text-sm leading-6 text-[rgba(15,23,42,0.68)]">
          {call.prop_block_reason}
        </p>
      ) : null}
    </section>
  );
}
