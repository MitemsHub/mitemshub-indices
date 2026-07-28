"use client";

import React from "react";
import type { ExecutionMode, FreshCallResponse, GuardianStatus, TrackedPosition } from "../../lib/contracts";
import {
  formatGuardianReason,
  formatGuardianState,
  formatMarketCopy,
  formatPrice,
  formatActionSummary,
} from "../../lib/formatters";

type TradeInstructionPanelProps = {
  call: FreshCallResponse | null;
  guardianStatus: GuardianStatus | null;
  trackedPosition?: TrackedPosition | null;
  executing?: boolean;
  executionMode?: ExecutionMode;
  onExecute?: () => void;
  onClose?: () => void;
  onSetExecutionMode?: (mode: ExecutionMode) => void;
};

function StatusBadge({ state }: { state: FreshCallResponse["guardian_state"] }) {
  const classMap: Record<string, string> = {
    confirmed: "status-badge--confirmed",
    actionable: "status-badge--actionable",
    failing: "status-badge--failing",
    cancelled: "status-badge--cancelled",
    forming: "status-badge--forming",
    unavailable: "status-badge--unavailable",
  };
  const cls = classMap[state] ?? "status-badge--unavailable";
  return <span className={`status-badge ${cls}`}>{formatGuardianState(state)}</span>;
}

function SignalStrengthBadge({ strength }: { strength: FreshCallResponse["signal_strength"] }) {
  if (!strength) return null;
  const config: Record<string, { label: string; cls: string; icon: string; tooltip: string }> = {
    strong_buy: {
      label: "STRONG BUY",
      cls: "bg-emerald-100 text-emerald-800 border-emerald-300 ring-1 ring-emerald-200",
      icon: "◆",
      tooltip: "High-confidence long — full execution",
    },
    weak_buy: {
      label: "WEAK BUY",
      cls: "bg-amber-50 text-amber-700 border-amber-300",
      icon: "⚠",
      tooltip: "Moderate-confidence long — reduced position sizing",
    },
    wait: {
      label: "MONITORING",
      cls: "bg-gray-100 text-gray-500 border-gray-200",
      icon: "○",
      tooltip: "Confidence below threshold — monitoring market",
    },
    weak_sell: {
      label: "WEAK SELL",
      cls: "bg-amber-50 text-amber-700 border-amber-300",
      icon: "⚠",
      tooltip: "Moderate-confidence short — reduced position sizing",
    },
    strong_sell: {
      label: "STRONG SELL",
      cls: "bg-rose-100 text-rose-800 border-rose-300 ring-1 ring-rose-200",
      icon: "◆",
      tooltip: "High-confidence short — full execution",
    },
  };
  const c = config[strength] ?? config.wait;
  const isStrong = strength.startsWith("strong");
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${c.cls}${isStrong ? " animate-pulse" : ""}`}
      title={c.tooltip}
    >
      <span className="text-xs">{c.icon}</span>
      {c.label}
    </span>
  );
}

function PositionSizingBadge({ sizing }: { sizing: FreshCallResponse["position_sizing"] }) {
  if (!sizing || sizing === "none") return null;
  const config: Record<string, { label: string; cls: string }> = {
    full: { label: "Full Size", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
    half: { label: "Half Size", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  };
  const c = config[sizing] ?? { label: sizing, cls: "bg-gray-100 text-gray-500 border-gray-200" };
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${c.cls}`}>
      {c.label}
    </span>
  );
}

export function TradeInstructionPanel({
  call,
  guardianStatus,
  trackedPosition = null,
  executing = false,
  executionMode = "paper",
  onExecute = () => {},
  onClose = () => {},
  onSetExecutionMode = () => {},
}: TradeInstructionPanelProps) {
  const effectiveGuardianState =
    guardianStatus?.guardian_state ?? call?.guardian_state ?? "unavailable";
  const executionStop = call?.execution_stop ?? call?.stop_loss ?? null;
  const primaryTarget = call?.primary_target ?? call?.take_profit ?? null;
  const thesisInvalidation = call?.thesis_invalidation ?? null;
  const hasStaleExecutionPlan =
    call?.trade_status === "valid" &&
    (effectiveGuardianState === "failing" || effectiveGuardianState === "cancelled");
  const showExecutionLevels =
    call?.entry !== null &&
    call?.entry !== undefined &&
    executionStop !== null &&
    executionStop !== undefined &&
    primaryTarget !== null &&
    primaryTarget !== undefined &&
    !hasStaleExecutionPlan;
  const canExecute = Boolean(
    showExecutionLevels &&
    call?.trade_status === "valid" &&
    !trackedPosition &&
    !hasStaleExecutionPlan &&
    !executing &&
    call?.entry &&
    call?.stop_loss &&
    call?.take_profit
  );
  const hasOpenPosition = trackedPosition !== null;
  const guardianReason = guardianStatus?.guardian_reason ?? call?.guardian_reason;
  const actionSummary = call
    ? effectiveGuardianState === "cancelled"
      ? "Do not execute this plan. The original setup is cancelled."
      : effectiveGuardianState === "failing"
        ? "Do not execute the old plan until you refresh the call."
        : effectiveGuardianState === "confirmed" || effectiveGuardianState === "actionable"
          ? formatActionSummary(call)
          : `Do not enter yet. ${formatGuardianReason(guardianReason)}`
    : null;

  return (
    <section className="surface rounded-2xl p-5 md:p-6">
      <p className="utility-copy text-[11px] uppercase tracking-[0.28em] text-[var(--text-label)]">
        Trade execution
      </p>
      <h3 className="display-serif mt-2 text-lg font-semibold text-[var(--text-strong)]">
        What to do now
      </h3>

      {call ? (
        <div className="mt-4 space-y-4">
          {/* Decision summary */}
          <p className="text-sm leading-6 text-[var(--text-body)]">
            {formatMarketCopy(call.decision_summary ?? call.why)}
          </p>

          {/* ── Graduated signal strength banner ────────────────── */}
          {call?.signal_strength && (
            <div className={`rounded-xl border px-4 py-3 flex items-center gap-3 transition-colors ${
              call.signal_strength === "strong_buy"
                ? "border-emerald-300 bg-emerald-50/80"
                : call.signal_strength === "strong_sell"
                  ? "border-rose-300 bg-rose-50/80"
                  : call.signal_strength === "wait"
                    ? "border-gray-200 bg-gray-50/80"
                    : "border-amber-200 bg-amber-50/80"
            }`}>
              <span className={`text-2xl ${
                call.signal_strength === "strong_buy"
                  ? "text-emerald-600"
                  : call.signal_strength === "strong_sell"
                    ? "text-rose-600"
                    : call.signal_strength === "wait"
                      ? "text-gray-400"
                      : "text-amber-600"
              }`}> {
                call.signal_strength === "strong_buy" ? "▲" :
                call.signal_strength === "strong_sell" ? "▼" :
                call.signal_strength === "wait" ? "●" :
                call.signal_strength.includes("buy") ? "△" : "▽"
              }</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <SignalStrengthBadge strength={call.signal_strength} />
                  <PositionSizingBadge sizing={call?.position_sizing ?? null} />
                </div>
                <p className={`mt-1 text-xs ${
                  call.signal_strength.startsWith("strong")
                    ? "text-emerald-700"
                    : call.signal_strength === "wait"
                      ? "text-gray-500"
                      : "text-amber-700"
                }`}>
                  {
                    call.signal_strength.startsWith("strong")
                      ? "Full execution ready — confidence meets threshold"
                      : call.signal_strength === "wait"
                        ? "No execution — monitoring market conditions"
                        : "Caution — confidence below full threshold, reduced position sizing"
                  }
                </p>
              </div>
            </div>
          )}

          {/* Setup status card */}
          <div className="info-card rounded-xl p-4">
            <p className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">
              Setup status
            </p>
            <div className="mt-2 flex items-center gap-2 flex-wrap">
              <StatusBadge state={effectiveGuardianState} />
              <SignalStrengthBadge strength={call?.signal_strength ?? null} />
              <PositionSizingBadge sizing={call?.position_sizing ?? null} />
            </div>
            {guardianReason ? (
              <p className="mt-2 text-xs leading-5 text-[var(--text-body)]">
                {formatGuardianReason(guardianReason)}
              </p>
            ) : null}
          </div>

          {/* ── Open position card ────────────────────────────── */}
          {hasOpenPosition && trackedPosition ? (
            <div className="info-card rounded-xl p-4 border border-[var(--accent-ink)]">
              <p className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">
                Open position
              </p>
              <dl className="mt-3 grid grid-cols-2 gap-3">
                {[
                  ["Direction", trackedPosition.direction === "buy" ? "Long" : "Short"],
                  ["Entry", formatPrice(trackedPosition.entry_price)],
                  ["Stop loss", formatPrice(trackedPosition.stop_loss)],
                  ["Take profit", formatPrice(trackedPosition.take_profit)],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)]">{label}</dt>
                    <dd className="mt-0.5 text-sm font-semibold text-[var(--text-strong)]">{value}</dd>
                  </div>
                ))}
              </dl>
              <button
                type="button"
                disabled={executing}
                onClick={onClose}
                className="primary-action mt-3 w-full rounded-xl bg-[var(--accent-danger)] text-white hover:brightness-[0.85] disabled:opacity-45"
              >
                {executing ? "Closing..." : "Close Position"}
              </button>
            </div>
          ) : null}

          {/* ── Execution levels ────────────────────────────────── */}
          {showExecutionLevels && !hasOpenPosition ? (
            <div className={`grid gap-3 ${thesisInvalidation !== null ? "md:grid-cols-4" : "md:grid-cols-3"}`}>
              <div className="info-card rounded-xl px-3.5 py-3">
                <dt className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">Entry</dt>
                <dd className="mt-1 text-sm font-semibold tabular-nums text-[var(--text-strong)]">
                  {formatPrice(call.entry)}
                </dd>
              </div>
              <div className="info-card rounded-xl px-3.5 py-3">
                <dt className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">Stop</dt>
                <dd className="mt-1 text-sm font-semibold tabular-nums text-[var(--accent-danger)]">
                  {formatPrice(executionStop)}
                </dd>
              </div>
              <div className="info-card rounded-xl px-3.5 py-3">
                <dt className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">Target</dt>
                <dd className="mt-1 text-sm font-semibold tabular-nums text-[var(--accent-positive)]">
                  {formatPrice(primaryTarget)}
                </dd>
              </div>
              {thesisInvalidation !== null ? (
                <div className="info-card rounded-xl px-3.5 py-3">
                  <dt className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">Invalidation</dt>
                  <dd className="mt-1 text-sm font-semibold tabular-nums text-[var(--accent-warn)]">
                    {formatPrice(thesisInvalidation)}
                  </dd>
                </div>
              ) : null}
            </div>
          ) : !hasOpenPosition ? (
            <div className="info-card rounded-xl p-4">
              <p className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">
                Execution levels
              </p>
              <p className="mt-2 text-xs leading-5 text-[var(--text-body)]">
                Entry, stop, and target stay hidden until the setup is confirmed.
                {hasStaleExecutionPlan ? " Do not use the old entry levels." : ""}
              </p>
            </div>
          ) : null}

          {/* ── Action card ──────────────────────────────────────── */}
          <div className="action-card rounded-xl px-4 py-4">
            <p className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">
              Action
            </p>
            <p className="mt-2 text-sm leading-6 text-[var(--text-strong)]">
              {actionSummary}
            </p>
          </div>

          {/* ── Execute block ──────────────────────────────────────── */}
          {!hasOpenPosition ? (
            <div className="space-y-3">
              {/* Execution mode toggle */}
              <div className="flex items-center gap-2.5">
                <span className="utility-copy text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)]">
                  Mode
                </span>
                <button
                  type="button"
                  aria-pressed={executionMode === "paper"}
                  className="mode-toggle rounded-full px-3 py-1 text-xs font-medium"
                  onClick={() => onSetExecutionMode("paper")}
                >
                  Paper
                </button>
                <button
                  type="button"
                  aria-pressed={executionMode === "live_mt5"}
                  className="mode-toggle rounded-full px-3 py-1 text-xs font-medium"
                  onClick={() => onSetExecutionMode("live_mt5")}
                >
                  Live MT5
                </button>
              </div>

              {/* Execute button */}
              <button
                type="button"
                disabled={!canExecute}
                onClick={onExecute}
                className="primary-action w-full rounded-xl bg-[var(--accent-ink)] text-white hover:bg-[var(--accent-ink-hover)] disabled:opacity-45"
              >
                {executing
                  ? "Executing..."
                  : executionMode === "live_mt5"
                    ? "Execute Trade (Live MT5)"
                    : "Execute Trade (Paper)"
                }
              </button>

              {/* Block reason */}
              {!canExecute && !executing ? (
                <p className="text-xs text-[var(--text-body)]">
                  {!call?.entry
                    ? "No entry price available. Wait for a valid trade plan."
                    : call?.trade_status !== "valid"
                      ? "Trade not valid. Confidence or conditions not met."
                      : trackedPosition
                        ? "Close existing position first."
                        : hasStaleExecutionPlan
                          ? "Setup is stale. Refresh the call."
                          : "Waiting for entry/stop/target levels to be calculated."}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="mt-4 py-8 text-center">
          <p className="text-sm leading-6 text-[var(--text-body)]">
            The action steps appear after a live reading has been pulled.
          </p>
        </div>
      )}
    </section>
  );
}
