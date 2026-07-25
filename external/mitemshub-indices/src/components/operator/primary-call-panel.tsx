import React from "react";
import type { FreshCallResponse, GuardianStatus, GuardianState } from "../../lib/contracts";
import {
  formatCallAge,
  formatCallHeadline,
  formatConfidence,
  formatGuardianReason,
  formatGuardianState,
  formatMarketCopy,
  formatNextStep,
  formatPrice,
  formatSymbol,
} from "../../lib/formatters";

type PrimaryCallPanelProps = {
  call: FreshCallResponse | null;
  guardianStatus: GuardianStatus | null;
  loading: boolean;
  onRetry?: () => void;
  retryLabel?: string;
};

function GuardianBadge({ state }: { state: FreshCallResponse["guardian_state"] }) {
  const classMap: Record<string, string> = {
    confirmed: "status-badge--confirmed",
    actionable: "status-badge--actionable",
    failing: "status-badge--failing",
    cancelled: "status-badge--cancelled",
    forming: "status-badge--forming",
    unavailable: "status-badge--unavailable",
  };
  const cls = classMap[state] ?? "status-badge--unavailable";
  return <span className={`status-badge ${cls}`}>{formatGuardianState(state as GuardianState)}</span>;
}

function DirectionIndicator({ direction }: { direction: string | null }) {
  if (!direction) return null;
  const isBuy = direction === "buy";
  return (
    <span className={`direction-badge ${isBuy ? "direction-badge--buy" : "direction-badge--sell"}`}>
      <span className={`pulse-dot ${isBuy ? "pulse-dot--positive" : "pulse-dot--danger"}`} aria-hidden="true" />
      {isBuy ? "Bullish" : "Bearish"}
    </span>
  );
}

export function PrimaryCallPanel({
  call,
  guardianStatus,
  loading,
  onRetry,
  retryLabel,
}: PrimaryCallPanelProps) {
  const guardianState = guardianStatus?.guardian_state ?? call?.guardian_state;
  const guardianReason = guardianStatus?.guardian_reason ?? call?.guardian_reason;
  const holdHorizonCopy =
    call?.hold_horizon_minutes === 60
      ? "Primary objective is modeled for the next hour."
      : call?.hold_horizon_minutes
        ? `Primary objective is modeled for the next ${call.hold_horizon_minutes} minutes.`
        : null;

  return (
    <section className="primary-panel surface rounded-2xl p-5 md:p-6">
      <p className="utility-copy text-[11px] uppercase tracking-[0.28em] text-[var(--text-label)]">
        Trade plan
      </p>

      {call ? (
        <>
          {/* Headline row */}
          <div className="mt-3 flex flex-wrap items-center gap-2.5">
            <h2 className="display-serif text-xl font-semibold text-[var(--text-strong)] md:text-2xl">
              {formatCallHeadline(call.call)}
            </h2>
            <span className="info-chip rounded-full px-2.5 py-0.5 text-xs font-medium">
              {formatSymbol(call.symbol)}
            </span>
            <GuardianBadge state={guardianState ?? "unavailable"} />
            {call.confidence !== null && call.confidence !== undefined && (
              <span className="info-chip rounded-full px-2.5 py-0.5 text-xs font-medium">
                Confidence&nbsp;{formatConfidence(call.confidence)}
              </span>
            )}
            {(call.direction_bias === "buy" || call.direction_bias === "sell") && (
              <DirectionIndicator direction={call.direction_bias} />
            )}
          </div>

          {/* Meta bar */}
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-[var(--text-muted)]">
            {call.call_age_seconds !== null && call.call_age_seconds !== undefined && (
              <span>Plan age: {formatCallAge(call.call_age_seconds)}</span>
            )}
            {call.current_close !== null && (
              <span>Price: {formatPrice(call.current_close)}</span>
            )}
            {call.reward_risk !== null && (
              <span>R:R {call.reward_risk.toFixed(1)}</span>
            )}
          </div>

          {/* Detail cards */}
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            <div className="info-card rounded-xl p-4">
              <p className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">
                Market picture
              </p>
              <p className="mt-2 text-sm leading-6 text-[var(--text-strong)]">
                {formatMarketCopy(call.why ?? call.decision_summary)}
              </p>
            </div>
            <div className="info-card rounded-xl p-4">
              <p className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">
                What needs to happen next
              </p>
              <p className="mt-2 text-sm leading-6 text-[var(--text-strong)]">
                {formatNextStep(call.wait_for)}
              </p>
              {holdHorizonCopy ? (
                <p className="mt-2 text-xs leading-5 text-[var(--text-body)]">
                  {holdHorizonCopy}
                </p>
              ) : null}
              {call.invalidates_if ? (
                <p className="mt-2 text-xs leading-5 text-[var(--text-body)]">
                  Thesis invalidates on {call.invalidates_if}.
                </p>
              ) : null}
            </div>
            <div className="info-card rounded-xl p-4">
              <p className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">
                Setup status
              </p>
              <div className="mt-2">
                <GuardianBadge state={guardianState ?? "unavailable"} />
              </div>
              <p className="mt-2 text-xs leading-5 text-[var(--text-body)]">
                {formatGuardianReason(guardianReason)}
              </p>
              {(guardianState === "unavailable" || guardianState === "forming") && onRetry && (
                <div className="mt-3 pt-3 border-t border-[var(--line-subtle)]">
                  <button
                    type="button"
                    className="primary-action w-full bg-[var(--accent-ink)] text-white hover:bg-[var(--accent-ink-hover)] text-xs py-2"
                    disabled={loading}
                    onClick={onRetry}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="23 4 23 10 17 10" />
                      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
                    </svg>
                    {retryLabel ?? "Reconnect & re-read"}
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Entry levels bar — only when setup is active */}
          {guardianState !== "failing" && guardianState !== "cancelled" && call.entry !== null && call.stop_loss !== null && call.take_profit !== null && (
            <div className="mt-4 grid gap-3 grid-cols-3">
              <div className="info-card rounded-xl px-3.5 py-2.5 text-center">
                <p className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">Entry</p>
                <p className="mt-1 text-base font-semibold tabular-nums text-[var(--accent-ink)]">
                  {formatPrice(call.entry)}
                </p>
              </div>
              <div className="info-card rounded-xl px-3.5 py-2.5 text-center">
                <p className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">Stop loss</p>
                <p className="mt-1 text-base font-semibold tabular-nums text-[var(--accent-danger)]">
                  {formatPrice(call.stop_loss)}
                </p>
              </div>
              <div className="info-card rounded-xl px-3.5 py-2.5 text-center">
                <p className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">Take profit</p>
                <p className="mt-1 text-base font-semibold tabular-nums text-[var(--accent-positive)]">
                  {formatPrice(call.take_profit)}
                </p>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="mt-6 flex flex-col items-center gap-4 py-8 text-center">
          <div className="pulse-dot pulse-dot--muted" aria-hidden="true" />
          <p className="text-sm leading-6 text-[var(--text-body)] max-w-md">
            Run a live read for Volatility 75 or 100 to load the current trade plan.
          </p>
          {onRetry && (
            <button
              type="button"
              className="primary-action bg-[var(--accent-ink)] text-white hover:bg-[var(--accent-ink-hover)]"
              disabled={loading}
              onClick={onRetry}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="23 4 23 10 17 10" />
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
              </svg>
              {retryLabel ?? "Retry"}
            </button>
          )}
        </div>
      )}

    </section>
  );
}
