import React from "react";
import type { AccountMode } from "../../lib/contracts";

type SymbolCode = "R_75" | "R_100";

type CommandBarProps = {
  accountMode: AccountMode;
  loading: boolean;
  onSelectMode: (mode: AccountMode) => void;
  onRequestPropMode: () => void;
  onRunSymbol: (symbol: SymbolCode) => void;
};

export function CommandBar({
  accountMode,
  loading,
  onSelectMode,
  onRequestPropMode,
  onRunSymbol,
}: CommandBarProps) {
  return (
    <section className="command-rail surface rounded-[2rem] p-6">
      <div className="grid gap-5 xl:grid-cols-[1.2fr_0.95fr_0.85fr] xl:items-end">
        <div>
          <p className="utility-copy text-xs uppercase tracking-[0.28em]">
            Operator workspace
          </p>
          <h1 className="mt-3 text-3xl font-semibold text-[var(--text-strong)] md:text-4xl">
            Get a live trade plan
          </h1>
          <p className="mt-3 max-w-xl text-sm leading-6 text-[var(--text-body)]">
            Choose Volatility 75 or Volatility 100 to pull the latest local
            market readout, trade plan, and risk framing.
          </p>
        </div>
        <div className="flex flex-wrap gap-3 xl:justify-center">
          <button
            type="button"
            aria-pressed={accountMode === "own_account"}
            className="mode-toggle rounded-full px-4 py-2 text-sm font-medium"
            onClick={() => onSelectMode("own_account")}
          >
            Own Account
          </button>
          <button
            type="button"
            aria-pressed={accountMode === "prop_firm"}
            className="mode-toggle rounded-full px-4 py-2 text-sm font-medium"
            onClick={onRequestPropMode}
          >
            Prop Firm
          </button>
        </div>

        <div
          className="flex flex-wrap items-center gap-3 xl:justify-end"
          aria-live="polite"
        >
          <button
            type="button"
            className="command-button rounded-xl px-4 py-3 text-sm font-semibold"
            disabled={loading}
            onClick={() => onRunSymbol("R_75")}
          >
            R_75
          </button>
          <button
            type="button"
            className="command-button rounded-xl px-4 py-3 text-sm font-semibold"
            disabled={loading}
            onClick={() => onRunSymbol("R_100")}
          >
            R_100
          </button>
          <p className="utility-copy min-w-[11rem] text-right text-xs uppercase tracking-[0.24em]">
            {loading ? "Pulling live market plan" : "Ready"}
          </p>
        </div>
      </div>
    </section>
  );
}
