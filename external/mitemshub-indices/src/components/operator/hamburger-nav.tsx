"use client";

import React, { useEffect } from "react";
import { XIcon } from "../../lib/icons";
import { useScrollLock } from "../../hooks/use-scroll-lock";
import type { AccountMode, TradingMode, ExecutionMode } from "../../lib/contracts";
import type { FreshCallResponse } from "../../lib/contracts";

type HamburgerNavProps = {
  open: boolean;
  /** The symbol currently being analysed, if any */
  activeSymbol: "R_75" | "R_100" | null;
  /** The latest live call response, used to show guardian state */
  currentCall: FreshCallResponse | null;
  accountMode: AccountMode;
  tradingMode: TradingMode;
  executionMode: ExecutionMode;
  onOpen: () => void;
  onClose: () => void;
  onSetAccountMode: (mode: AccountMode) => void;
  onRequestPropMode: () => void;
  onSetTradingMode: (mode: TradingMode) => void;
  onSetExecutionMode: (mode: ExecutionMode) => void;
};

function MenuIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  );
}



export function HamburgerNav({
  open,
  activeSymbol,
  currentCall,
  accountMode,
  tradingMode,
  executionMode,
  onOpen,
  onClose,
  onSetAccountMode,
  onRequestPropMode,
  onSetTradingMode,
  onSetExecutionMode,
}: HamburgerNavProps) {
  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  // Prevent body scroll when overlay is open
  useScrollLock(open);

  return (
    <>
      {/* Hamburger button — always mounted, visible only on mobile via CSS */}
      <button
        type="button"
        className="hamburger-btn"
        onClick={open ? onClose : onOpen}
        aria-label={open ? "Close menu" : "Open menu"}
        aria-expanded={open}
      >
        <MenuIcon />
      </button>

      {/* Overlay backdrop — always mounted, fades via CSS opacity transition */}
      <div
        className={`mobile-nav-overlay${open ? " mobile-nav-overlay--open" : ""}`}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer — always mounted so the slide-in/out CSS transition plays
          on both open and close. When closed, aria-hidden + inert
          + 0x0 clipping ensures it's invisible and non-interactive. */}
      <aside
        className={`mobile-nav${open ? " mobile-nav--open" : ""}`}
        role="dialog"
        aria-modal={open ? "true" : undefined}
        aria-label="Settings menu"
        aria-hidden={!open}
        style={!open ? { clip: "rect(0,0,0,0)", clipPath: "inset(50%)", position: "fixed" } : undefined}
      >
          <button
            type="button"
            className="close-btn"
            onClick={onClose}
            aria-label="Close menu"
          >
            <XIcon />
          </button>

          {/* Account mode */}
          <div className="mobile-nav-section">
            <h3>Account</h3>
            <div className="mode-row">
              <button
                type="button"
                aria-pressed={accountMode === "own_account"}
                className="mode-toggle rounded-full px-4 py-2 text-sm font-medium"
                onClick={() => { onSetAccountMode("own_account"); onClose(); }}
              >
                Personal
              </button>
              <button
                type="button"
                aria-pressed={accountMode === "prop_firm"}
                className="mode-toggle rounded-full px-4 py-2 text-sm font-medium"
                onClick={() => { onRequestPropMode(); onClose(); }}
              >
                Prop Firm
              </button>
            </div>
          </div>

          {/* Strategy mode */}
          <div className="mobile-nav-section">
            <h3>Strategy</h3>
            <div className="mode-row">
              <button
                type="button"
                aria-pressed={tradingMode === "sniper"}
                className="mode-toggle rounded-full px-4 py-2 text-sm font-medium"
                onClick={() => { onSetTradingMode("sniper"); onClose(); }}
              >
                Sniper
              </button>
              <button
                type="button"
                aria-pressed={tradingMode === "active_trader"}
                className="mode-toggle rounded-full px-4 py-2 text-sm font-medium"
                onClick={() => { onSetTradingMode("active_trader"); onClose(); }}
              >
                Active
              </button>
            </div>
          </div>

          {/* Execution mode */}
          <div className="mobile-nav-section">
            <h3>Execution</h3>
            <div className="mode-row">
              <button
                type="button"
                aria-pressed={executionMode === "paper"}
                className="mode-toggle rounded-full px-4 py-2 text-sm font-medium"
                onClick={() => { onSetExecutionMode("paper"); onClose(); }}
              >
                Paper
              </button>
              <button
                type="button"
                aria-pressed={executionMode === "live_mt5"}
                className="mode-toggle rounded-full px-4 py-2 text-sm font-medium"
                onClick={() => { onSetExecutionMode("live_mt5"); onClose(); }}
              >
                Live MT5
              </button>
            </div>
          </div>

          {/* Active symbol indicator */}
          {activeSymbol && (
            <div className="mobile-nav-section">
              <h3>Active symbol</h3>
              <p className="text-sm font-medium text-[var(--text-strong)]">
                {activeSymbol === "R_75" ? "Volatility 75" : "Volatility 100"}
                {currentCall && (
                  <span className="ml-2 text-xs text-[var(--text-muted)]">
                    Status:{" "}
                    {currentCall.guardian_state === "confirmed"
                      ? "Confirmed"
                      : currentCall.guardian_state === "actionable"
                        ? "Actionable"
                        : currentCall.guardian_state === "failing"
                          ? "Failing"
                          : "Idle"}
                  </span>
                )}
              </p>
            </div>
          )}
        </aside>
    </>
  );
}
