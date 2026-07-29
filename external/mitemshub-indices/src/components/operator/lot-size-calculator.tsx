"use client";

import { useState, useMemo, useEffect } from "react";

type LotSizeCalculatorProps = {
  accountEquity?: number;
  entryPrice?: number | null;
  stopLoss?: number | null;
  takeProfit?: number | null;
  symbol?: string;
};

/**
 * Built-in lot size calculator for Blueberry Markets prop accounts.
 *
 * Automatically calculates the correct lot size based on:
 * - Account equity
 * - Stop loss distance
 * - Risk percentage (1.5% max for prop accounts)
 * - Symbol-specific point values
 */
export function LotSizeCalculator({
  accountEquity = 100_000,
  entryPrice = null,
  stopLoss = null,
  takeProfit = null,
  symbol = "R_100",
}: LotSizeCalculatorProps) {
  const [equity, setEquity] = useState(accountEquity);
  const [riskPct, setRiskPct] = useState(1.5);
  const [customEntry, setCustomEntry] = useState(entryPrice?.toString() ?? "");
  const [customStop, setCustomStop] = useState(stopLoss?.toString() ?? "");
  const [customTP, setCustomTP] = useState(takeProfit?.toString() ?? "");

  // Update fields when props change (e.g., new signal arrives)
  const effectiveEntry = customEntry !== "" ? parseFloat(customEntry) : entryPrice;
  const effectiveStop = customStop !== "" ? parseFloat(customStop) : stopLoss;
  const effectiveTP = customTP !== "" ? parseFloat(customTP) : takeProfit;

  // Track whether user has manually edited each field
  const [entryEdited, setEntryEdited] = useState(false);
  const [stopEdited, setStopEdited] = useState(false);
  const [tpEdited, setTpEdited] = useState(false);

  // Sync inputs when signal props change (new signal arrives)
  // Only sync if the user hasn't manually edited the field
  useEffect(() => {
    if (!entryEdited) setCustomEntry(entryPrice?.toString() ?? "");
  }, [entryPrice, entryEdited]);
  useEffect(() => {
    if (!stopEdited) setCustomStop(stopLoss?.toString() ?? "");
  }, [stopLoss, stopEdited]);
  useEffect(() => {
    if (!tpEdited) setCustomTP(takeProfit?.toString() ?? "");
  }, [takeProfit, tpEdited]);

  // Blueberry Markets synthetic index contract size: 100 units per lot
  // 1 lot = 100 units, so a 1-point move = $100 P&L per lot
  const contractSize = 100;

  const calculation = useMemo(() => {
    if (
      !effectiveEntry || !effectiveStop ||
      !Number.isFinite(effectiveEntry) || !Number.isFinite(effectiveStop)
    ) {
      return null;
    }

    const stopDistance = Math.abs(effectiveEntry - effectiveStop);
    if (stopDistance <= 0) return null;

    const riskAmount = equity * (riskPct / 100);
    // Lot size = risk_amount / (stop_distance * contract_size)
    // For Blueberry: 1 lot = 100 units, so 1 point = $100 P&L per lot
    const lotSize = riskAmount / (stopDistance * contractSize);

    // Round down to nearest 0.01 lot
    const roundedLots = Math.floor(lotSize * 100) / 100;

    // Calculate actual risk with rounded lots
    const actualRisk = roundedLots * stopDistance * contractSize;
    const actualRiskPct = (actualRisk / equity) * 100;

    // Calculate reward if TP is provided
    let rewardRisk = null;
    let potentialProfit = null;
    if (effectiveTP && Number.isFinite(effectiveTP)) {
      const tpDistance = Math.abs(effectiveTP - effectiveEntry);
      rewardRisk = tpDistance / stopDistance;
      potentialProfit = roundedLots * tpDistance * contractSize;
    }

    // Daily loss limit (4%)
    const dailyLossLimit = equity * 0.04;
    // Max drawdown (10%)
    const maxDrawdown = equity * 0.10;

    return {
      lotSize: roundedLots,
      stopDistance,
      riskAmount,
      actualRisk,
      actualRiskPct,
      rewardRisk,
      potentialProfit,
      dailyLossLimit,
      maxDrawdown,
      entry: effectiveEntry,
      stop: effectiveStop,
      tp: effectiveTP,
    };
  }, [equity, riskPct, effectiveEntry, effectiveStop, effectiveTP, symbol]);

  return (
    <div className="surface rounded-xl p-3 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
          Lot Size Calculator
        </p>
        <span className="text-[10px] text-[var(--text-muted)] font-mono">
          Blueberry Markets
        </span>
      </div>

      {/* Input fields */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[10px] text-[var(--text-label)] block mb-1">
            Account Equity ($)
          </label>
          <input
            type="number"
            value={equity}
            onChange={(e) => setEquity(parseFloat(e.target.value) || 0)}
            className="w-full rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2 py-1.5 text-[11px] font-mono text-[var(--text-body)] focus:outline-none focus:border-[var(--accent-ink)]"
          />
        </div>
        <div>
          <label className="text-[10px] text-[var(--text-label)] block mb-1">
            Risk %
          </label>
          <input
            type="number"
            value={riskPct}
            onChange={(e) => setRiskPct(parseFloat(e.target.value) || 0)}
            step={0.1}
            min={0.1}
            max={2.0}
            className="w-full rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2 py-1.5 text-[11px] font-mono text-[var(--text-body)] focus:outline-none focus:border-[var(--accent-ink)]"
          />
        </div>
        <div>
          <label className="text-[10px] text-[var(--text-label)] block mb-1">
            Entry Price
          </label>              <input
                type="number"
                value={customEntry}
                onChange={(e) => { setCustomEntry(e.target.value); setEntryEdited(true); }}
                onFocus={() => setEntryEdited(true)}
                placeholder={entryPrice?.toString() ?? "—"}
                step={0.01}
                className="w-full rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2 py-1.5 text-[11px] font-mono text-[var(--text-body)] focus:outline-none focus:border-[var(--accent-ink)]"
              />
        </div>
        <div>
          <label className="text-[10px] text-[var(--text-label)] block mb-1">
            Stop Loss
          </label>              <input
                type="number"
                value={customStop}
                onChange={(e) => { setCustomStop(e.target.value); setStopEdited(true); }}
                onFocus={() => setStopEdited(true)}
                placeholder={stopLoss?.toString() ?? "—"}
                step={0.01}
                className="w-full rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2 py-1.5 text-[11px] font-mono text-[var(--text-body)] focus:outline-none focus:border-[var(--accent-ink)]"
              />
        </div>
        <div className="col-span-2">
          <label className="text-[10px] text-[var(--text-label)] block mb-1">
            Take Profit (optional)
          </label>              <input
                type="number"
                value={customTP}
                onChange={(e) => { setCustomTP(e.target.value); setTpEdited(true); }}
                onFocus={() => setTpEdited(true)}
                placeholder={takeProfit?.toString() ?? "—"}
                step={0.01}
                className="w-full rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2 py-1.5 text-[11px] font-mono text-[var(--text-body)] focus:outline-none focus:border-[var(--accent-ink)]"
              />
        </div>
      </div>

      {/* Results */}
      {calculation ? (
        <div className="space-y-2">
          {/* Primary result — lot size */}
          <div className="rounded-lg border border-[var(--accent-ink)] bg-[var(--accent-ink-soft)] px-3 py-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-[var(--accent-ink)] font-medium uppercase tracking-[0.12em]">
                Recommended Lot Size
              </span>
              <span className="text-lg font-bold font-mono text-[var(--accent-ink)]">
                {calculation.lotSize.toFixed(2)}
              </span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-3 text-[10px] text-[var(--text-body)]">
              <span>Risk: ${calculation.actualRisk.toFixed(0)} ({calculation.actualRiskPct.toFixed(2)}%)</span>
              <span>Stop: {calculation.stopDistance.toFixed(2)} pts</span>
              {calculation.rewardRisk && (
                <span>R:R = 1:{calculation.rewardRisk.toFixed(1)}</span>
              )}
            </div>
          </div>

          {/* Quick reference */}
          <div className="grid grid-cols-3 gap-2 text-[10px]">
            <div className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2 py-1.5 text-center">
              <p className="text-[var(--text-label)]">Daily Limit</p>
              <p className="font-mono font-semibold text-[var(--accent-danger)]">
                ${calculation.dailyLossLimit.toFixed(0)}
              </p>
            </div>
            <div className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2 py-1.5 text-center">
              <p className="text-[var(--text-label)]">Max DD</p>
              <p className="font-mono font-semibold text-[var(--accent-warn)]">
                ${calculation.maxDrawdown.toFixed(0)}
              </p>
            </div>
            {calculation.potentialProfit && (
              <div className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2 py-1.5 text-center">
                <p className="text-[var(--text-label)]">Potential P</p>
                <p className="font-mono font-semibold text-[var(--accent-positive)]">
                  ${calculation.potentialProfit.toFixed(0)}
                </p>
              </div>
            )}
          </div>

          {/* Risk gauge */}
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-[var(--text-label)]">Risk:</span>
            <div className="flex-1 h-1.5 rounded-full bg-[var(--line-subtle)] overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-300 ${
                  calculation.actualRiskPct > 1.5
                    ? "bg-[var(--accent-danger)]"
                    : calculation.actualRiskPct > 1.0
                      ? "bg-[var(--accent-warn)]"
                      : "bg-[var(--accent-positive)]"
                }`}
                style={{ width: `${Math.min((calculation.actualRiskPct / 2) * 100, 100)}%` }}
              />
            </div>
            <span className={`text-[10px] font-mono font-semibold ${
              calculation.actualRiskPct > 1.5
                ? "text-[var(--accent-danger)]"
                : calculation.actualRiskPct > 1.0
                  ? "text-[var(--accent-warn)]"
                  : "text-[var(--accent-positive)]"
            }`}>
              {calculation.actualRiskPct > 1.5 ? "HIGH" : calculation.actualRiskPct > 1.0 ? "MODERATE" : "SAFE"}
            </span>
          </div>
        </div>
      ) : (
        <p className="text-[10px] text-[var(--text-muted)] italic text-center py-2">
          Enter entry price and stop loss to calculate lot size
        </p>
      )}
    </div>
  );
}
