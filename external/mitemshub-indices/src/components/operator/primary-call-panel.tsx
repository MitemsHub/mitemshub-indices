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

function VenueBadge({ venue }: { venue: NonNullable<FreshCallResponse["venue"]> }) {
  if (venue === "mt5") {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full border border-[var(--accent-success)]/40 bg-[var(--accent-success-soft)] px-2 py-0.5 text-[10px] font-medium text-[var(--accent-success)]"
        title="Levels are on the Deriv SYN price scale"
      >
        MT5 venue
      </span>
    );
  }
  if (venue === "deriv") {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full border border-[var(--accent-warn)]/40 bg-[var(--accent-warn-soft)] px-2 py-0.5 text-[10px] font-medium text-[var(--accent-warn)]"
        title="Deriv 1HZ scale — levels are NOT comparable to the Deriv SYN platform"
      >
        Deriv scale
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border border-[var(--accent-muted)]/40 bg-[var(--accent-muted-soft)] px-2 py-0.5 text-[10px] font-medium text-[var(--text-muted)]"
      title="Levels come from the local CSV corpus"
    >
      CSV venue
    </span>
  );
}

function Stage3Verification({ block }: { block: NonNullable<FreshCallResponse["stage3"]> }) {
  // Collapsed gate: below-floor call types are always suppressed (held back),
  // so there is no annotate-escape state to render anymore.
  const suppressed = block.state === "suppressed";
  const gated = block.state === "gated";
  const annotated = block.state === "annotated";
  const stillLearning = block.evidence_status === "still_learning";
  const noData = block.evidence_status === "no_data";
  const stateClass = suppressed
    ? "bg-[var(--accent-danger)]/10 text-[var(--accent-danger)] border border-[var(--accent-danger)]/25"
    : gated
      ? "bg-[var(--accent-positive)]/10 text-[var(--accent-positive)] border border-[var(--accent-positive)]/25"
      : stillLearning
        ? "bg-[var(--accent-info)]/10 text-[var(--accent-info)] border border-[var(--accent-info)]/25"
        : annotated
          ? "bg-[var(--accent-warn)]/10 text-[var(--accent-warn)] border border-[var(--accent-warn)]/25"
          : noData
            ? "bg-[var(--line-subtle)]/40 text-[var(--text-muted)] border border-[var(--line-subtle)]"
            : "bg-[var(--accent-warn)]/10 text-[var(--accent-warn)] border border-[var(--accent-warn)]/25";
  const stateLabel = suppressed
    ? "Suppressed"
    : gated
      ? "Proven"
      : stillLearning
        ? "Still learning"
        : annotated
          ? "Proven — horizon pending"
          : noData
            ? "Unverified"
            : "Empirical";
  const stateDot = suppressed
    ? "bg-[var(--accent-danger)]"
    : gated
      ? "bg-[var(--accent-positive)]"
      : stillLearning
        ? "bg-[var(--accent-info)]"
        : annotated
          ? "bg-[var(--accent-warn)]"
          : "bg-[var(--text-muted)]";
  const sampleCopy =
    block.empirical_sample_count > 0 && stillLearning
      ? `${block.empirical_sample_count}/${block.min_samples ?? 10} scored`
      : block.empirical_sample_count > 0
        ? `${block.empirical_sample_count} scored`
        : "no outcomes yet";

  return (
    <div className={`mt-3 rounded-lg border px-3 py-2.5 ${suppressed ? "border-[var(--accent-danger)]/30 bg-[var(--accent-danger)]/5" : "border-[var(--line-subtle)] bg-[var(--bg-panel-muted)]"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${stateClass}`}>
          <span className={`inline-block w-1.5 h-1.5 rounded-full ${stateDot}`} aria-hidden="true" />
          {stateLabel}
        </span>
        {block.empirical_target_hit_rate !== null && block.empirical_target_hit_rate !== undefined && (
          <span className="text-xs font-semibold text-[var(--text-strong)]">
            {formatConfidence(block.empirical_target_hit_rate)} hit rate
            <span className="ml-1 text-[10px] font-normal text-[var(--text-muted)]">({sampleCopy})</span>
          </span>
        )}
        {(block.empirical_target_hit_rate === null || block.empirical_target_hit_rate === undefined) && (
          <span className="text-[11px] text-[var(--text-muted)]">({sampleCopy})</span>
        )}
        <span className="text-[11px] font-mono text-[var(--text-muted)]">{block.trigger_type}</span>
        {block.hit_rate_floor !== undefined && block.hit_rate_floor > 0 && (
          <span className="text-[11px] text-[var(--text-muted)]">floor {formatConfidence(block.hit_rate_floor)}</span>
        )}
        {block.horizon_verdict && (
          <span className={`text-[11px] font-medium ${block.horizon_verdict === "calibrated" ? "text-[var(--accent-positive)]" : "text-[var(--accent-warn)]"}`}>
            horizon: {block.horizon_verdict === "calibrated" ? "calibrated" : block.horizon_verdict}
          </span>
        )}
        {block.p50_mult !== null && block.p50_mult !== undefined && (
          <span className="text-[11px] font-mono text-[var(--text-muted)]" title="Calibrated 60s range multipliers (tune-bands output)">
            bands ×{block.p50_mult.toFixed(2)}/×{block.p90_mult != null ? block.p90_mult.toFixed(2) : "—"}
          </span>
        )}
      </div>
      {(() => {
        const fourH = block.horizon_forecast?.["4h"];
        const forecast = fourH?.forecast;
        if (!forecast || forecast.range_p50_price == null || forecast.current_close == null) return null;
        // Honest label: only call the bands "calibrated" when the walk-forward
        // verdict for this horizon is calibrated — otherwise they are prior-based
        // (no tuned multipliers on disk) and must not be oversold.
        const calibrated = fourH?.verdict === "calibrated";
        const p50Pct = ((forecast.range_p50_price / forecast.current_close) * 100) / 2;
        const p90Pct =
          forecast.range_p90_price != null ? ((forecast.range_p90_price / forecast.current_close) * 100) / 2 : null;
        return (
          <p className="mt-1.5 text-[11px] leading-5 text-[var(--text-muted)]">
            {calibrated ? "Calibrated 4h vol bands" : "4h vol bands (uncalibrated)"}: p50 ±{p50Pct.toFixed(1)}% ·
            {p90Pct != null ? ` p90 ±${p90Pct.toFixed(1)}%` : " p90 —"}
            {forecast.expected_low_p50 != null && forecast.expected_high_p50 != null
              ? ` (${formatPrice(forecast.expected_low_p50)} – ${formatPrice(forecast.expected_high_p50)})`
              : ""}
          </p>
        );
      })()}
      {suppressed && block.suppressed_call ? (
        <p className="mt-1.5 text-[11px] leading-5 text-[var(--accent-danger)]">
          {block.suppressed_call} calls are held back — this setup type is below the verified floor.
        </p>
      ) : null}
      {block.sizing ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
              block.sizing.level === "full"
                ? "bg-[var(--accent-positive)]/10 text-[var(--accent-positive)] border border-[var(--accent-positive)]/25"
                : block.sizing.level === "half"
                  ? "bg-[var(--accent-warn)]/10 text-[var(--accent-warn)] border border-[var(--accent-warn)]/25"
                  : block.sizing.level === "paper_only"
                    ? "bg-[var(--accent-info)]/10 text-[var(--accent-info)] border border-[var(--accent-info)]/25"
                    : "bg-[var(--accent-danger)]/10 text-[var(--accent-danger)] border border-[var(--accent-danger)]/25"
            }`}
          >
            {block.sizing.level === "full"
              ? "Full size"
              : block.sizing.level === "half"
                ? "Half size"
                : block.sizing.level === "paper_only"
                  ? "Paper only"
                  : "Held back"}
          </span>
          <span className="text-[11px] leading-5 text-[var(--text-body)]">{block.sizing.reason}</span>
        </div>
      ) : null}
      {block.note ? <p className="mt-1.5 text-[11px] leading-5 text-[var(--text-body)]">{block.note}</p> : null}
    </div>
  );
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
          {/* Staleness indicator for cached calls */}
          {call.call_age_seconds !== null && call.call_age_seconds !== undefined && call.call_age_seconds > 300 && (
            <div className="mt-2 flex items-center gap-2 rounded-lg border border-[var(--accent-warn)] bg-[var(--accent-warn-soft)] px-3 py-2">
              <span className="inline-block w-2 h-2 rounded-full bg-[var(--accent-warn)] flex-shrink-0" aria-hidden="true" />
              <p className="text-xs text-[var(--accent-warn)]">
                Showing cached plan from {formatCallAge(call.call_age_seconds)} ago — click Refresh for live data
              </p>
            </div>
          )}

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
                {call.stage3?.state === "gated"
                  ? "Verified&nbsp;"
                  : call.stage3?.state === "annotated"
                    ? "Empirical&nbsp;"
                    : call.stage3?.state === "suppressed"
                      ? "Suppressed&nbsp;"
                      : "Confidence&nbsp;"}
                {formatConfidence(call.confidence)}
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
            {call.venue && <VenueBadge venue={call.venue} />}
          </div>

          {/* Stage-3 empirical verification strip */}
          {call.stage3 && <Stage3Verification block={call.stage3} />}

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
              {call.band_gate && !call.band_gate.signal_emitted && (
                <div className="mt-3 rounded-lg border border-[var(--line-subtle)] bg-[var(--surface-raised)] px-3 py-2.5">
                  <p className="utility-copy text-[10px] uppercase tracking-[0.18em] text-[var(--text-label)]">
                    Why no call yet
                  </p>
                  <p className="mt-1.5 text-xs leading-5 text-[var(--text-body)]">
                    {call.band_gate.warmup_ok === false ? (
                      <>
                        Building candle history — {call.band_gate.candles ?? 0}/
                        {call.band_gate.needed_candles ?? 60} bars warmed up.
                      </>
                    ) : (
                      <>
                        Waiting on{" "}
                        {call.band_gate.vol_extended
                          ? "price displacement"
                          : "a volatility spike"}
                        : vol {call.band_gate.vol_ratio != null ? `${call.band_gate.vol_ratio.toFixed(2)}/${call.band_gate.vol_extended_ratio?.toFixed(2) ?? "1.30"}` : "—"}
                        {call.band_gate.z_dev != null
                          ? ` · displacement ${Math.abs(call.band_gate.z_dev).toFixed(2)}/${call.band_gate.z_entry?.toFixed(1) ?? "1.0"}σ`
                          : ""}
                      </>
                    )}
                  </p>
                  {call.band_gate.waiting_on ? (
                    <p className="mt-1 text-[10px] text-[var(--text-muted)]">
                      {call.band_gate.waiting_on}
                    </p>
                  ) : null}
                </div>
              )}
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
                    {/* An unavailable read means something failed ("re-read" is
                        honest).  A forming setup is normal market state — the
                        engine is connected and working, so the button just
                        refreshes the plan rather than implying a failure. */}
                    {guardianState === "unavailable"
                      ? (retryLabel ?? "Reconnect & re-read")
                      : "Refresh plan"}
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Entry levels bar — only when setup is active */}
          {guardianState !== "failing" && guardianState !== "cancelled" && call.entry !== null && call.stop_loss !== null && call.take_profit !== null && (
            <div className="mt-4 grid gap-3 grid-cols-3">
              <div className="info-card rounded-xl px-3.5 py-2.5 text-center">
                <p className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">
                  {call.entry_chased ? "Entry (market)" : "Entry"}
                </p>
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
          {call.entry_chased && (
            <div className="mt-2 rounded-lg border border-[var(--line-subtle)] bg-[var(--surface-raised)] px-3 py-2.5">
              <p className="text-xs leading-5 text-[var(--text-body)]">
                <span className="font-semibold text-[var(--accent-ink)]">
                  Entry re-anchored
                </span>
                {" "}— the market moved past the original entry
                {call.original_entry != null ? ` (${formatPrice(call.original_entry)})` : ""}.
                {" "}Enter at <span className="font-semibold">market</span>:{" "}
                <span className="font-semibold tabular-nums">{formatPrice(call.entry)}</span>.
              </p>
            </div>
          )}
        </>
      ) : loading ? (
        <div className="mt-6 flex flex-col items-center gap-4 py-10 text-center">
          <div
            className="h-9 w-9 animate-spin rounded-full border-2 border-[var(--line-subtle)] border-t-[var(--accent-ink)]"
            role="status"
            aria-label="Analyzing the market"
          />
          <div className="max-w-md">
            <p className="text-sm font-medium leading-6 text-[var(--text-strong)]">
              Analyzing the market — building your trade plan…
            </p>
            <p className="mt-1 text-xs leading-5 text-[var(--text-muted)]">
              Reading the latest market data, running the strategy engines, and calibrating the
              1-hour volatility band for the call's stop and target. This takes a few seconds.
            </p>
          </div>
        </div>
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
