"use client";

import React, { useEffect, useRef } from "react";
import { XIcon } from "../lib/icons";
import type { AccountMode, TradingMode } from "../lib/contracts";

type MobileNavProps = {
  open: boolean;
  onClose: () => void;
  accountMode: AccountMode;
  tradingMode: TradingMode;
  onSelectMode: (mode: AccountMode) => void;
  onRequestPropMode: () => void;
  onSelectTradingMode: (mode: TradingMode) => void;
};

function HamburgerIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  );
}



export function MobileNavTrigger({
  onClick,
  open,
}: {
  onClick: () => void;
  open: boolean;
}) {
  return (
    <button
      type="button"
      className="mobile-nav-trigger"
      onClick={onClick}
      aria-label={open ? "Close menu" : "Open menu"}
      aria-expanded={open}
    >
      {open ? <XIcon size={20} /> : <HamburgerIcon />}
    </button>
  );
}

export function MobileNavDrawer({
  open,
  onClose,
  accountMode,
  tradingMode,
  onSelectMode,
  onRequestPropMode,
  onSelectTradingMode,
}: MobileNavProps) {
  const drawerRef = useRef<HTMLDivElement>(null);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  // Prevent body scroll when drawer is open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  return (
    <>
      {/* Backdrop */}
      <div
        className={`mobile-nav-backdrop ${open ? "mobile-nav-backdrop--open" : ""}`}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer */}
      <div
        ref={drawerRef}
        className={`mobile-nav-drawer ${open ? "mobile-nav-drawer--open" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label="Navigation settings"
      >
        <div className="mobile-nav-drawer__header">
          <p className="text-[11px] font-medium uppercase tracking-[0.24em] text-[var(--text-muted)]">
            Settings
          </p>
          <button
            type="button"
            onClick={onClose}
            className="mobile-nav-close"
            aria-label="Close menu"
          >
            <XIcon size={20} />
          </button>
        </div>

        <div className="mobile-nav-drawer__body space-y-5">
          {/* ── Account mode ──────────────────────── */}
          <fieldset>
            <legend className="mb-2 text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">
              Account
            </legend>
            <div className="flex gap-2">
              <button
                type="button"
                aria-pressed={accountMode === "own_account"}
                className="mode-toggle rounded-full px-4 py-2 text-sm font-medium flex-1"
                onClick={() => { onSelectMode("own_account"); onClose(); }}
              >
                Personal
              </button>
              <button
                type="button"
                aria-pressed={accountMode === "prop_firm"}
                className="mode-toggle rounded-full px-4 py-2 text-sm font-medium flex-1"
                onClick={() => { onRequestPropMode(); onClose(); }}
              >
                Prop Firm
              </button>
            </div>
          </fieldset>

          {/* ── Trading mode ──────────────────────── */}
          <fieldset>
            <legend className="mb-2 text-[10px] uppercase tracking-[0.2em] text-[var(--text-label)]">
              Strategy
            </legend>
            <div className="flex gap-2">
              <button
                type="button"
                aria-pressed={tradingMode === "sniper"}
                className="mode-toggle rounded-full px-4 py-2 text-sm font-medium flex-1"
                onClick={() => { onSelectTradingMode("sniper"); onClose(); }}
              >
                Sniper
              </button>
              <button
                type="button"
                aria-pressed={tradingMode === "active_trader"}
                className="mode-toggle rounded-full px-4 py-2 text-sm font-medium flex-1"
                onClick={() => { onSelectTradingMode("active_trader"); onClose(); }}
              >
                Active
              </button>
            </div>
          </fieldset>

          {/* ── Status ────────────────────────────── */}
          <p className="text-xs text-[var(--text-body)] leading-5">
            These settings control how the engine evaluates the market. Changes
            take effect on the next live read.
          </p>
        </div>
      </div>
    </>
  );
}
