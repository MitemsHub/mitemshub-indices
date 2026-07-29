import React from "react";
import type { AccountMode, TradingMode } from "../../lib/contracts";

type SymbolCode = "R_75" | "R_100";

type CommandBarProps = {
  accountMode: AccountMode;
  activeSymbol: SymbolCode | null;
  loading: boolean;
  loadingElapsedSeconds: number;
  tradingMode: TradingMode;
  onSelectMode: (mode: AccountMode) => void;
  onRequestPropMode: () => void;
  onRunSymbol: (symbol: SymbolCode) => void;
  onSelectTradingMode: (mode: TradingMode) => void;
  onStopRefresh: () => void;
};

function ElapsedTimer({ seconds }: { seconds: number }) {
  const display = `${String(Math.min(seconds, 9999)).padStart(2, "0")}s`;
  return (
    <span className="utility-copy inline-flex items-center gap-1.5 rounded-full border border-[var(--line-subtle)] bg-[var(--surface-raised)] px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-[var(--text-strong)]">
      <span className="loading-pulse" aria-hidden="true" />
      {display}
    </span>
  );
}

function RunButton({
  symbol,
  activeSymbol,
  loading,
  onClick,
}: {
  symbol: SymbolCode;
  activeSymbol: SymbolCode | null;
  loading: boolean;
  onClick: () => void;
}) {
  const isActive = activeSymbol === symbol;
  const isRunning = loading && isActive;
  const label = symbol === "R_75" ? "Volatility 75" : "Volatility 100";
  const shortLabel = symbol === "R_75" ? "V75" : "V100";

  return (
    <button
      type="button"
      className={`command-button rounded-xl px-3.5 py-2 text-xs font-semibold transition-all duration-200 ${
        isActive
          ? "command-button--active ring-2 ring-[var(--accent-ink)] ring-offset-1 ring-offset-[var(--surface-default)]"
          : ""
      }`}
      disabled={loading}
      onClick={onClick}
      title={`Run live analysis for ${label} Index`}
      aria-label={`${symbol} — ${isRunning ? "loading" : label}`}
    >
      <span className="hidden sm:inline">{label}</span>
      <span className="sm:hidden">{shortLabel}</span>
    </button>
  );
}

export function CommandBar({
  accountMode,
  activeSymbol,
  loading,
  loadingElapsedSeconds,
  tradingMode,
  onSelectMode,
  onRequestPropMode,
  onRunSymbol,
  onSelectTradingMode,
  onStopRefresh,
}: CommandBarProps) {
  return (
    <section className="command-rail surface rounded-2xl p-4 md:p-5">
      {/* ── Row 1: Branding (full width) ───────────────────── */}
      <div>
        <p className="utility-copy text-[11px] uppercase tracking-[0.28em] text-[var(--text-label)]">
          MitemsHub Indices
        </p>
        <h1 className="display-serif mt-2 text-xl font-semibold text-[var(--text-strong)] md:text-2xl">
          Live trade intelligence
        </h1>
        {activeSymbol ? (
          <div>
            <p className="mt-1.5 max-w-lg text-sm leading-6 text-[var(--text-body)]">
              {loading
                ? loadingElapsedSeconds >= 10
                  ? "Still loading… The snapshot is taking longer than expected."
                  : "Fetching the latest local market reading and trade plan…"
                : "Latest market structure analysis, trade plan, and risk assessment are displayed below."}
            </p>

            {/* ── 15-second waiting banner ──────────────────────────
                When the snapshot takes more than 15 seconds, show a
                pulsing reassurance banner with a visible Stop prompt.
                The 30-second auto-abort provides the safety net; this
                banner bridges the gap between "normal wait" and abort. */}
            {loading && loadingElapsedSeconds >= 15 && (
              <div
                className="mt-3 waiting-banner"
                role="status"
                aria-live="polite"
              >
                <span className="waiting-banner__dot" aria-hidden="true" />
                <span className="waiting-banner__text">
                  Still waiting… Tap <strong>Stop</strong> to cancel
                </span>
              </div>
            )}
          </div>
        ) : (
          <p className="mt-1.5 max-w-lg text-sm leading-6 text-[var(--text-body)]">
            Run a live read on Volatility 75 or Volatility 100 to get the
            latest market structure analysis, trade plan, and risk assessment.
          </p>
        )}
      </div>

      {/* ── Row 2: Controls ribbon ─────────────────────────── */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        {/* ├─ Account ──────────────────────────────────── */}
        <div className="desktop-controls flex flex-wrap items-center gap-2">
          <span className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)] mr-1">
            Account
          </span>
          <button
            type="button"
            aria-pressed={accountMode === "own_account"}
            className="mode-toggle rounded-full px-3.5 py-1.5 text-xs font-medium"
            onClick={() => onSelectMode("own_account")}
          >
            Personal
          </button>
          <button
            type="button"
            aria-pressed={accountMode === "prop_firm"}
            className="mode-toggle rounded-full px-3.5 py-1.5 text-xs font-medium"
            onClick={onRequestPropMode}
          >
            Prop Firm
          </button>
        </div>

        {/* ├─ Symbol ─────────────────────────────────────── */}
        <div className="flex flex-wrap items-center gap-2" aria-live="polite">
          <span className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)] mr-1">
            Symbol
          </span>
          <RunButton
            symbol="R_75"
            activeSymbol={activeSymbol}
            loading={loading}
            onClick={() => onRunSymbol("R_75")}
          />
          <RunButton
            symbol="R_100"
            activeSymbol={activeSymbol}
            loading={loading}
            onClick={() => onRunSymbol("R_100")}
          />

          {/* Status / timer */}
          <div className="flex items-center gap-2 ml-1">
            {loading ? (
              <ElapsedTimer seconds={loadingElapsedSeconds} />
            ) : (
              activeSymbol && (
                <span className="utility-copy inline-flex items-center gap-1.5 rounded-full border border-[var(--line-subtle)] bg-[var(--surface-raised)] px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-[var(--accent-positive)]">
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent-positive)]" aria-hidden="true" />
                  Live
                </span>
              )
            )}
            <p className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">
              {loading ? "Pulling data…" : activeSymbol ? "Ready" : "Idle"}
            </p>
          </div>

          {/* Stop / Refresh button */}
          <button
            type="button"
            onClick={onStopRefresh}
            disabled={!activeSymbol && !loading}
            className={`rounded-xl px-3 py-2 text-xs font-semibold transition-all duration-150 ${
              loading
                ? "bg-[var(--accent-danger)] text-white hover:brightness-[0.85] active:scale-95"
                : "bg-[var(--surface-raised)] text-[var(--text-strong)] hover:bg-[var(--line-subtle)] border border-[var(--line-subtle)] active:scale-95"
            } disabled:opacity-40 disabled:pointer-events-none`}
            title={loading ? "Cancel the current analysis" : "Re-run analysis for the active symbol"}
          >
            {loading ? "Stop" : "Refresh"}
          </button>
        </div>

        {/* ├─ Strategy ───────────────────────────────────── */}
        <div className="desktop-controls flex flex-wrap items-center gap-2">
          <span className="utility-copy text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)] mr-1">
            Strategy
          </span>
          <button
            type="button"
            aria-pressed={tradingMode === "sniper"}
            title="Conservative. Fewer, higher-conviction trade plans."
            className="mode-toggle rounded-full px-3.5 py-1.5 text-xs font-medium"
            onClick={() => onSelectTradingMode("sniper")}
          >
            Sniper
          </button>
          <button
            type="button"
            aria-pressed={tradingMode === "active_trader"}
            title="Frequent. More trade plans with calculated risk."
            className="mode-toggle rounded-full px-3.5 py-1.5 text-xs font-medium"
            onClick={() => onSelectTradingMode("active_trader")}
          >
            Active
          </button>
          <button
            type="button"
            aria-pressed={tradingMode === "volatility_harvest"}
            title="Exploits variance clustering. Trades only on GARCH mean-reversion signals."
            className="mode-toggle rounded-full px-3.5 py-1.5 text-xs font-medium"
            onClick={() => onSelectTradingMode("volatility_harvest")}
          >
            Vol Harvest
          </button>
        </div>
      </div>
    </section>
  );
}
