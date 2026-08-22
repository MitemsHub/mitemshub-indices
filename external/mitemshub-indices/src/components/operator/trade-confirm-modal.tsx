"use client";

import React, { useEffect, useRef, useState } from "react";
import { XIcon } from "../../lib/icons";
import { formatPrice } from "../../lib/formatters";
import type { ExecutionMode, FreshCallResponse } from "../../lib/contracts";

/** Human-readable explanations for common MT5 retcodes */
const MT5_ERROR_MESSAGES: Record<number, { title: string; fix: string }> = {
  10026: {
    title: "AutoTrading disabled by broker",
    fix: "Contact Deriv support to enable automated/EAs trading on your account. Also verify you are using the Master Password, not the Investor (read-only) password.",
  },
  10027: {
    title: "AutoTrading disabled in MT5 terminal",
    fix: "Click the 'Algo Trading' button on the MT5 toolbar to enable it, or go to Tools > Options > Expert Advisors and check 'Allow automated trading'.",
  },
  10016: {
    title: "Invalid Stop Loss / Take Profit",
    fix: "Your SL or TP is too close to the current price. The broker requires a minimum distance (stops level). Adjust your levels further from the current price.",
  },
  10014: {
    title: "Invalid lot size",
    fix: "The trade volume is outside the allowed range for this symbol. Check the minimum and maximum lot size in MT5 Market Watch.",
  },
  10019: {
    title: "Insufficient funds",
    fix: "Not enough free margin to open this position. Reduce the lot size or deposit more funds.",
  },
  10018: {
    title: "Market is closed",
    fix: "Trading is not available right now — the market is closed (weekend or holiday). Wait until the market reopens.",
  },
  10017: {
    title: "Trading is disabled",
    fix: "Trading is disabled for this symbol or account type. Contact your broker to verify.",
  },
  10021: {
    title: "No price quotes available",
    fix: "The broker is not providing price data for this symbol right now. Check your MT5 connection and try again.",
  },
  10004: {
    title: "Price has changed (requote)",
    fix: "The price moved while the order was being placed. Click Execute again to retry with the latest price.",
  },
};

/**
 * Try to extract the MT5 retcode from an error message string.
 * Handles formats like 'Retcode: 10026' or 'retcode: 10026' or 'code 10026'.
 */
function extractRetcode(msg: string): number | null {
  const match = msg.match(/(?:retcode|code)[:\s]*(\d{4,5})/i);
  return match ? parseInt(match[1], 10) : null;
}

/** Get a user-friendly error display from a raw error string */
function humanizeMt5Error(raw: string): { title: string; fix: string } | null {
  const code = extractRetcode(raw);
  if (code !== null && MT5_ERROR_MESSAGES[code]) {
    return MT5_ERROR_MESSAGES[code];
  }
  return null;
}

type TradeConfirmModalProps = {
  open: boolean;
  call: FreshCallResponse;
  executionMode: ExecutionMode;
  executionError?: string | null;
  onConfirm: (params: { entry: number; stopLoss: number; takeProfit: number }) => void;
  onCancel: () => void;
};

export function TradeConfirmModal({
  open,
  call,
  executionMode,
  executionError = null,
  onConfirm,
  onCancel,
}: TradeConfirmModalProps) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [countdown, setCountdown] = useState(3);
  const [editEntry, setEditEntry] = useState(0);
  const [editStopLoss, setEditStopLoss] = useState(0);
  const [editTakeProfit, setEditTakeProfit] = useState(0);
  const [entryModified, setEntryModified] = useState(false);
  const [stopModified, setStopModified] = useState(false);
  const [tpModified, setTpModified] = useState(false);
  const confirmBtnRef = useRef<HTMLButtonElement>(null);

  // Reset state when modal opens
  useEffect(() => {
    if (open) {
      setAcknowledged(false);
      setCountdown(3);
      setEditEntry(call.entry ?? 0);
      setEditStopLoss(call.stop_loss ?? call.entry ?? 0);
      setEditTakeProfit(call.take_profit ?? call.entry ?? 0);
      setEntryModified(false);
      setStopModified(false);
      setTpModified(false);
    }
  }, [open, call]);

  // Countdown timer before confirm button is enabled
  useEffect(() => {
    if (!open || countdown <= 0) return;
    const timer = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [open, countdown]);

  // Focus the confirm button when it becomes enabled
  useEffect(() => {
    if (countdown <= 0 && acknowledged) {
      confirmBtnRef.current?.focus();
    }
  }, [countdown, acknowledged]);

  if (!open) return null;

  const isLive = executionMode === "live_mt5";
  const isBuy = call.direction_bias === "buy";
  const direction = call.direction_bias?.toUpperCase() ?? "UNKNOWN";
  const levelsValid = editEntry > 0 && editStopLoss > 0 && editTakeProfit > 0
    ? isBuy
      ? editStopLoss < editEntry && editTakeProfit > editEntry
      : editStopLoss > editEntry && editTakeProfit < editEntry
    : false;
  const directionColor =
    call.direction_bias === "buy"
      ? "var(--accent-positive)"
      : call.direction_bias === "sell"
        ? "var(--accent-danger)"
        : "var(--text-body)";

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm"
        style={{
          animation: "fadeIn 200ms var(--ease-out)",
        }}
        onClick={onCancel}
        aria-hidden="true"
      />

      {/* Modal */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Confirm trade execution"
        className="fixed inset-0 z-[101] flex items-center justify-center p-4"
        style={{ overflowY: 'auto', WebkitOverflowScrolling: 'touch', overscrollBehavior: 'contain' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="w-full max-w-md rounded-2xl border border-[var(--line-subtle)] bg-[var(--bg-panel-strong)] shadow-[var(--shadow-elevated)] overflow-hidden flex flex-col my-auto"
          style={{
            animation: "modalSlideIn 300ms var(--ease-out)",
            maxHeight: 'min(80vh, 480px)',
          }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--line-subtle)]">
            <div className="flex items-center gap-2.5">
              {isLive && (
                <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[var(--accent-danger-soft)] text-[var(--accent-danger)] text-xs font-semibold">
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-danger)] animate-pulse" />
                  LIVE
                </span>
              )}
              {call.position_sizing && call.position_sizing !== "none" && (
                <span
                  className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold border ${
                    call.position_sizing === "full"
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : "bg-amber-50 text-amber-700 border-amber-200"
                  }`}
                >
                  {call.position_sizing === "full" ? "◆ Full Size" : "◇ Half Size"}
                </span>
              )}
              {call.position_sizing === "none" && (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-gray-100 text-gray-500 border border-gray-200">
                  ○ No Execution
                </span>
              )}
              <h2 className="text-sm font-semibold text-[var(--text-strong)]">
                Confirm Trade Execution
              </h2>
            </div>
            <button
              type="button"
              onClick={onCancel}
              className="flex items-center justify-center w-8 h-8 rounded-lg hover:bg-[var(--bg-surface-hover)] transition-colors"
              aria-label="Cancel"
            >
              <XIcon />
            </button>
          </div>

          {/* Body */}
          <div className="px-5 py-4 space-y-4 overflow-y-auto flex-1 min-h-0">
            {/* Direction banner */}
            <div
              className="flex items-center justify-between rounded-xl px-4 py-3"
              style={{
                background:
                  call.direction_bias === "buy"
                    ? "rgba(15, 107, 87, 0.08)"
                    : "rgba(196, 68, 58, 0.08)",
                border: `1px solid ${
                  call.direction_bias === "buy"
                    ? "rgba(15, 107, 87, 0.2)"
                    : "rgba(196, 68, 58, 0.2)"
                }`,
              }}
            >
              <div>
                <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">
                  Direction
                </p>
                <p
                  className="text-lg font-bold"
                  style={{ color: directionColor }}
                >
                  {direction}
                </p>
              </div>
              <div className="text-right">
                <p className="text-xs uppercase tracking-[0.16em] text-[var(--text-muted)]">
                  Symbol
                </p>
                <p className="text-sm font-semibold text-[var(--text-strong)]">
                  {call.symbol === "R_100" ? "Volatility 100" : "Volatility 75"}
                </p>
              </div>
            </div>

            {/* Editable Price levels */}
            <div className="space-y-2">
              <div className="flex items-center gap-3">
                <label className="w-20 text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)] shrink-0">
                  Entry
                </label>
                <div className="flex-1 relative">
                  <input
                    type="number"
                    step="0.01"
                    value={editEntry}
                    min="0.01"
                    onChange={(e) => { const v = parseFloat(e.target.value); if (!isNaN(v)) { setEditEntry(v); setEntryModified(true); } }}
                    className="w-full rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel)] px-3 py-2 text-sm font-bold tabular-nums text-[var(--text-strong)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-ink)] focus:border-[var(--accent-ink)] transition-all"
                  />
                  {entryModified && (
                    <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] font-medium text-[var(--accent-warn)] bg-[var(--accent-warn-soft)] px-1.5 py-0.5 rounded">
                      Modified
                    </span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <label className="w-20 text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)] shrink-0">
                  Stop Loss
                </label>
                <div className="flex-1 relative">
                  <input
                    type="number"
                    step="0.01"
                    value={editStopLoss}
                    min="0.01"
                    onChange={(e) => { const v = parseFloat(e.target.value); if (!isNaN(v)) { setEditStopLoss(v); setStopModified(true); } }}
                    className="w-full rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel)] px-3 py-2 text-sm font-bold tabular-nums text-[var(--accent-danger)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-danger)] focus:border-[var(--accent-danger)] transition-all"
                  />
                  {stopModified && (
                    <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] font-medium text-[var(--accent-warn)] bg-[var(--accent-warn-soft)] px-1.5 py-0.5 rounded">
                      Modified
                    </span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <label className="w-20 text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)] shrink-0">
                  Take Profit
                </label>
                <div className="flex-1 relative">
                  <input
                    type="number"
                    step="0.01"
                    value={editTakeProfit}
                    min="0.01"
                    onChange={(e) => { const v = parseFloat(e.target.value); if (!isNaN(v)) { setEditTakeProfit(v); setTpModified(true); } }}
                    className="w-full rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel)] px-3 py-2 text-sm font-bold tabular-nums text-[var(--accent-positive)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-positive)] focus:border-[var(--accent-positive)] transition-all"
                  />
                  {tpModified && (
                    <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] font-medium text-[var(--accent-warn)] bg-[var(--accent-warn-soft)] px-1.5 py-0.5 rounded">
                      Modified
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Reset button if any field was modified */}
            {(entryModified || stopModified || tpModified) && (
              <button
                type="button"
                onClick={() => {
                  setEditEntry(call.entry ?? 0);
                  setEditStopLoss(call.stop_loss ?? call.entry ?? 0);
                  setEditTakeProfit(call.take_profit ?? call.entry ?? 0);
                  setEntryModified(false);
                  setStopModified(false);
                  setTpModified(false);
                }}
                className="text-xs text-[var(--accent-ink)] hover:underline"
              >
                Reset to suggested levels
              </button>
            )}

            {/* Risk summary — reflects edited values */}
            {editEntry > 0 && editStopLoss > 0 && editTakeProfit > 0 && editEntry !== editStopLoss && (
              <div className="flex items-center justify-between text-xs text-[var(--text-muted)] px-1">
                <span>
                  Risk:{" "}
                  <span className="font-medium text-[var(--text-body)]">
                    {formatPrice(Math.abs(editEntry - editStopLoss))}
                  </span>
                </span>
                <span>
                  Reward:{" "}
                  <span className="font-medium text-[var(--text-body)]">
                    {formatPrice(Math.abs(editTakeProfit - editEntry))}
                  </span>
                </span>
                <span>
                  R:R{" "}
                  <span className="font-semibold text-[var(--text-strong)]">
                    {editEntry !== editStopLoss ? (Math.abs(editTakeProfit - editEntry) / Math.abs(editEntry - editStopLoss)).toFixed(1) : "—"}
                  </span>
                </span>
              </div>
            )}

            {/* Directional validation hint */}
            {!levelsValid && editEntry > 0 && (
              <div className="rounded-lg border border-[var(--accent-warn)] bg-[var(--accent-warn-soft)] px-4 py-2.5">
                <p className="text-xs text-[var(--accent-warn)]">
                  {isBuy
                    ? "For a BUY: Stop Loss must be below Entry, Take Profit above Entry."
                    : "For a SELL: Stop Loss must be above Entry, Take Profit below Entry."}
                </p>
              </div>
            )}

            {/* Live warning */}
            {isLive && !executionError && (
              <div className="rounded-xl border border-[var(--accent-danger)] bg-[var(--accent-danger-soft)] px-4 py-3">
                <p className="text-xs font-semibold text-[var(--accent-danger)]">
                  ⚠ Live MT5 Execution
                </p>
                <p className="mt-1 text-xs leading-5 text-[var(--text-body)]">
                  This will place a real order on your Deriv MT5 account.
                  Make sure you have verified the entry, stop loss, and take profit levels.
                </p>
              </div>
            )}

            {/* Execution error */}
            {executionError && (() => {
              const friendly = humanizeMt5Error(executionError);
              return (
                <div className="rounded-xl border border-[var(--accent-danger)] bg-[var(--accent-danger-soft)] px-4 py-3">
                  <p className="text-xs font-semibold text-[var(--accent-danger)]">
                    ✗ {friendly?.title ?? "Order Failed"}
                  </p>
                  {friendly && (
                    <p className="mt-1 text-xs leading-5 text-[var(--text-body)] font-medium">
                      {friendly.fix}
                    </p>
                  )}
                  <p className="mt-1 text-[10px] leading-4 text-[var(--text-muted)] font-mono">
                    {executionError}
                  </p>
                </div>
              );
            })()}

            {/* Confirmation checkbox */}
            <label className="flex items-start gap-3 cursor-pointer group">
              <div className="relative mt-0.5">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(e) => setAcknowledged(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-4 h-4 rounded border border-[var(--line-strong)] bg-white peer-checked:bg-[var(--accent-ink)] peer-checked:border-[var(--accent-ink)] transition-colors" />
                <svg
                  className="absolute inset-0 w-4 h-4 text-white opacity-0 peer-checked:opacity-100 transition-opacity"
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M3 8l3 3 7-7" />
                </svg>
              </div>
              <span className="text-xs leading-5 text-[var(--text-body)] group-hover:text-[var(--text-strong)] transition-colors">
                I have reviewed the trade parameters and understand the risks involved.
              </span>
            </label>
          </div>

          {/* Footer — fixed at bottom, never scrolls */}
          <div className="flex items-center gap-3 px-5 py-4 border-t border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] shrink-0">
            <button
              type="button"
              onClick={onCancel}
              className="flex-1 rounded-xl border border-[var(--line-subtle)] bg-white px-4 py-2.5 text-sm font-medium text-[var(--text-body)] hover:bg-[var(--bg-surface-hover)] transition-colors"
            >
              Cancel
            </button>
            <div className="flex-1">
              <button
                ref={confirmBtnRef}
                type="button"
                disabled={!acknowledged || countdown > 0 || !levelsValid}
                onClick={() => onConfirm({ entry: editEntry, stopLoss: editStopLoss, takeProfit: editTakeProfit })}
                className={`w-full rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition-all ${
                  isLive
                    ? "bg-[var(--accent-danger)] hover:brightness-90"
                    : "bg-[var(--accent-ink)] hover:bg-[var(--accent-ink-hover)]"
                } disabled:opacity-40 disabled:cursor-not-allowed`}
              >
                {countdown > 0
                  ? `Wait ${countdown}s...`
                  : isLive
                    ? "Execute Live Trade"
                    : "Execute Paper Trade"}
              </button>
              {/* Disabled reason hint */}
              {countdown <= 0 && !acknowledged && !levelsValid && (
                <p className="mt-1.5 text-center text-[10px] text-[var(--text-muted)]">
                  Check the box above and fix price levels to enable
                </p>
              )}
              {countdown <= 0 && !acknowledged && levelsValid && (
                <p className="mt-1.5 text-center text-[10px] text-[var(--text-muted)]">
                  Check the confirmation box above to enable
                </p>
              )}
              {countdown <= 0 && acknowledged && !levelsValid && (
                <p className="mt-1.5 text-center text-[10px] text-[var(--text-muted)]">
                  Fix the price levels above to enable
                </p>
              )}
            </div>
          </div>
        </div>
      </div>

      <style jsx>{`
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes modalSlideIn {
          from {
            opacity: 0;
            transform: translateY(16px) scale(0.97);
          }
          to {
            opacity: 1;
            transform: translateY(0) scale(1);
          }
        }
      `}</style>
    </>
  );
}
