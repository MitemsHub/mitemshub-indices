import React from "react";
import type { FreshCallResponse, GuardianStatus } from "../../lib/contracts";
import {
  formatCallHeadline,
  formatConfidence,
  formatGuardianReason,
  formatGuardianState,
  formatMarketCopy,
  formatNextStep,
} from "../../lib/formatters";
import { LoadingState } from "./loading-state";

type PrimaryCallPanelProps = {
  call: FreshCallResponse | null;
  guardianStatus: GuardianStatus | null;
  loading: boolean;
};

export function PrimaryCallPanel({
  call,
  guardianStatus,
  loading,
}: PrimaryCallPanelProps) {
  const guardianState = guardianStatus?.guardian_state ?? call?.guardian_state;
  const guardianReason = guardianStatus?.guardian_reason ?? call?.guardian_reason;

  return (
    <section className="primary-panel surface rounded-[2.5rem] p-6 md:p-8">
      <p className="utility-copy text-xs uppercase tracking-[0.28em]">
        Trade plan
      </p>
      {call ? (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <h2 className="text-3xl font-semibold text-[var(--text-strong)] md:text-5xl">
              {formatCallHeadline(call.call)}
            </h2>
            <span className="info-chip rounded-full px-3 py-1 text-sm">
              {call.symbol}
            </span>
            <span className="info-chip rounded-full px-3 py-1 text-sm">
              Confidence {formatConfidence(call.confidence)}
            </span>
          </div>
          <div className="mt-6 grid gap-4 md:grid-cols-3">
            <div className="info-card rounded-[1.5rem] p-5">
              <p className="utility-copy text-xs uppercase tracking-[0.24em]">
                Market picture
              </p>
              <p className="mt-2 text-base leading-7 text-[var(--text-strong)]">
                {formatMarketCopy(call.why ?? call.decision_summary)}
              </p>
            </div>
            <div className="info-card rounded-[1.5rem] p-5">
              <p className="utility-copy text-xs uppercase tracking-[0.24em]">
                What needs to happen next
              </p>
              <p className="mt-2 text-base leading-7 text-[var(--text-strong)]">
                {formatNextStep(call.wait_for)}
              </p>
            </div>
            <div className="info-card rounded-[1.5rem] p-5">
              <p className="utility-copy text-xs uppercase tracking-[0.24em]">
                Setup status
              </p>
              <p className="mt-2 text-base leading-7 text-[var(--text-strong)]">
                {formatGuardianState(guardianState)}
              </p>
              <p className="mt-2 text-sm leading-6 text-[var(--text-body)]">
                {formatGuardianReason(guardianReason)}
              </p>
            </div>
          </div>
        </>
      ) : (
        <p className="mt-4 text-base text-[var(--text-body)]">
          Run a live read for Volatility 75 or 100 to load the current trade plan.
        </p>
      )}
      {loading ? <LoadingState /> : null}
    </section>
  );
}
