"use client";

import React, { useEffect, useRef, useState } from "react";
import { XIcon } from "../../lib/icons";
import { formatPrice } from "../../lib/formatters";
import type { ExecutionMode, FreshCallResponse } from "../../lib/contracts";

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
  const direction = call.direction_bias?.toUpperCase() ?? "UNKNOWN";
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
            maxHeight: 'min(90vh, 560px)',
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
                    min="0"
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
                    min="0"
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
                    min="0"
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

            {/* Live warning */}
            {isLive && !executionError && (
              <div className="rounded-xl border border-[var(--accent-danger)] bg-[var(--accent-danger-soft)] px-4 py-3">
                <p className="text-xs font-semibold text-[var(--accent-danger)]">
                  ⚠ Live MT5 Execution
                </p>
                <p className="mt-1 text-xs leading-5 text-[var(--text-body)]">
                  This will place a real order on your Blueberry Markets MT5 account.
                  Make sure you have verified the entry, stop loss, and take profit levels.
                </p>
              </div>
            )}

            {/* Execution error */}
            {executionError && (
              <div className="rounded-xl border border-[var(--accent-danger)] bg-[var(--accent-danger-soft)] px-4 py-3">
                <p className="text-xs font-semibold text-[var(--accent-danger)]">
                  ✗ Order Failed
                </p>
                <p className="mt-1 text-xs leading-5 text-[var(--text-body)]">
                  {executionError}
                </p>
              </div>
            )}

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
            <button
              ref={confirmBtnRef}
              type="button"
              disabled={!acknowledged || countdown > 0}
              onClick={() => onConfirm({ entry: editEntry, stopLoss: editStopLoss, takeProfit: editTakeProfit })}
              className={`flex-1 rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition-all ${
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
