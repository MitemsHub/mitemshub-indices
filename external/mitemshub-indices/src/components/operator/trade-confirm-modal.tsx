"use client";

import React, { useEffect, useRef, useState } from "react";
import { XIcon } from "../../lib/icons";
import { formatPrice } from "../../lib/formatters";
import type { ExecutionMode, FreshCallResponse } from "../../lib/contracts";

type TradeConfirmModalProps = {
  open: boolean;
  call: FreshCallResponse;
  executionMode: ExecutionMode;
  onConfirm: () => void;
  onCancel: () => void;
};

export function TradeConfirmModal({
  open,
  call,
  executionMode,
  onConfirm,
  onCancel,
}: TradeConfirmModalProps) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [countdown, setCountdown] = useState(3);
  const confirmBtnRef = useRef<HTMLButtonElement>(null);

  // Reset state when modal opens
  useEffect(() => {
    if (open) {
      setAcknowledged(false);
      setCountdown(3);
    }
  }, [open]);

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
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="w-full max-w-md rounded-2xl border border-[var(--line-subtle)] bg-[var(--bg-panel-strong)] shadow-[var(--shadow-elevated)] overflow-hidden"
          style={{
            animation: "modalSlideIn 300ms var(--ease-out)",
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
          <div className="px-5 py-4 space-y-4">
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

            {/* Price levels */}
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-xl bg-[var(--bg-panel-muted)] px-3 py-2.5 text-center">
                <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">
                  Entry
                </p>
                <p className="mt-0.5 text-sm font-bold tabular-nums text-[var(--text-strong)]">
                  {formatPrice(call.entry)}
                </p>
              </div>
              <div className="rounded-xl bg-[var(--bg-panel-muted)] px-3 py-2.5 text-center">
                <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">
                  Stop Loss
                </p>
                <p className="mt-0.5 text-sm font-bold tabular-nums text-[var(--accent-danger)]">
                  {formatPrice(call.stop_loss)}
                </p>
              </div>
              <div className="rounded-xl bg-[var(--bg-panel-muted)] px-3 py-2.5 text-center">
                <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-muted)]">
                  Take Profit
                </p>
                <p className="mt-0.5 text-sm font-bold tabular-nums text-[var(--accent-positive)]">
                  {formatPrice(call.take_profit)}
                </p>
              </div>
            </div>

            {/* Risk summary */}
            {call.entry && call.stop_loss && call.take_profit && (
              <div className="flex items-center justify-between text-xs text-[var(--text-muted)] px-1">
                <span>
                  Risk:{" "}
                  <span className="font-medium text-[var(--text-body)]">
                    {formatPrice(Math.abs(call.entry - (call.stop_loss ?? call.entry)))}
                  </span>
                </span>
                <span>
                  Reward:{" "}
                  <span className="font-medium text-[var(--text-body)]">
                    {formatPrice(Math.abs((call.take_profit ?? call.entry) - call.entry))}
                  </span>
                </span>
                <span>
                  R:R{" "}
                  <span className="font-semibold text-[var(--text-strong)]">
                    {call.reward_risk?.toFixed(1) ?? "—"}
                  </span>
                </span>
              </div>
            )}

            {/* Live warning */}
            {isLive && (
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

          {/* Footer */}
          <div className="flex items-center gap-3 px-5 py-4 border-t border-[var(--line-subtle)] bg-[var(--bg-panel-muted)]">
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
              onClick={onConfirm}
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
