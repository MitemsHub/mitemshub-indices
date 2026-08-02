"use client";

import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { XIcon, ChevronLeftIcon } from "../../lib/icons";
import { useScrollLock } from "../../hooks/use-scroll-lock";
import type { AccountMode, TradingMode, ExecutionMode } from "../../lib/contracts";
import type { FreshCallResponse } from "../../lib/contracts";

type HamburgerNavProps = {
  open: boolean;
  activeSymbol: "R_75" | "R_100" | null;
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
  const [mounted, setMounted] = useState(false);
  const [animPhase, setAnimPhase] = useState<"closed" | "entering" | "open" | "closing">("closed");

  // Track mount state for portal
  useEffect(() => {
    setMounted(true);
  }, []);

  // Two-step open/close animation
  useEffect(() => {
    if (open) {
      // Step 1: remove --hidden so the drawer is painted at translateX(100%)
      setAnimPhase("entering");
      // Step 2: on the next frame, add --open to slide to translateX(0)
      const raf = requestAnimationFrame(() => {
        setAnimPhase("open");
      });
      return () => cancelAnimationFrame(raf);
    } else {
      // Step 1: remove --open so the drawer slides to translateX(100%)
      setAnimPhase("closing");
      // Step 2: after the 420ms CSS transition completes, add --hidden
      const timer = setTimeout(() => {
        setAnimPhase("closed");
      }, 420);
      return () => clearTimeout(timer);
    }
  }, [open]);

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

  const drawerContent = (
    <>
      {/* Overlay backdrop */}
      <div
        className={`mobile-nav-overlay${open ? " mobile-nav-overlay--open" : ""}`}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer */}
      <aside
        className={`mobile-nav${animPhase === "open" ? " mobile-nav--open" : ""}${animPhase === "closed" ? " mobile-nav--hidden" : ""}`}
        role="dialog"
        aria-modal={open ? "true" : undefined}
        aria-label="Settings menu"
        aria-hidden={!open}
      >
        <div className="flex items-center gap-2 mb-4">
          <button
            type="button"
            className="back-btn"
            onClick={onClose}
            aria-label="Go back"
          >
            <ChevronLeftIcon />
          </button>
          <span className="text-sm font-semibold text-[var(--text-strong)]">Settings</span>
        </div>

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

        {/* Strategy mode (sniper only) */}
        <div className="mobile-nav-section">
          <h3>Strategy</h3>
          <div className="mode-row">
            <button
              type="button"
              aria-pressed={tradingMode === "sniper"}
              className="mode-toggle rounded-full px-4 py-2 text-sm font-medium"
              onClick={() => { onSetTradingMode("sniper"); onClose(); }}
            >
              Sniper (Swing)
            </button>
          </div>
          <p className="text-xs text-[var(--text-muted)] mt-1">4–6 hour swing trades only</p>
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

  return (
    <>
      {/* Hamburger button — stays inside the normal flow */}
      <button
        type="button"
        className="hamburger-btn"
        onClick={open ? onClose : onOpen}
        aria-label={open ? "Close menu" : "Open menu"}
        aria-expanded={open}
      >
        <MenuIcon />
      </button>

      {/* Portal: overlay + drawer escape the .app-shell isolation stacking context */}
      {mounted && createPortal(drawerContent, document.body)}
    </>
  );
}
