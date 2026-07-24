"use client";

import React from "react";

type MobileBottomNavTab = "execute" | "history" | "settings";

type MobileBottomNavProps = {
  activeTab: MobileBottomNavTab | null;
  onExecute: () => void;
  onHistory: () => void;
  onSettings: () => void;
};

/**
 * Trigger haptic feedback via the Vibration API.
 * Only fires on devices that support navigator.vibrate() (most Android
 * browsers, some iOS webviews). Desktop browsers silently no-op.
 * Pattern: a short 10ms pulse — light enough to feel but not annoying.
 */
function triggerHaptic() {
  try {
    if (typeof navigator !== "undefined" && "vibrate" in navigator) {
      navigator.vibrate(10);
    }
  } catch {
    // Silently ignore — haptic is a progressive enhancement
  }
}

function ExecuteIcon({ active }: { active: boolean }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
      stroke={active ? "var(--accent-positive)" : "currentColor"}
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}

function HistoryIcon({ active }: { active: boolean }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
      stroke={active ? "var(--accent-ink)" : "currentColor"}
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  );
}

function SettingsIcon({ active }: { active: boolean }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
      stroke={active ? "var(--accent-ink)" : "currentColor"}
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

export function MobileBottomNav({
  activeTab,
  onExecute,
  onHistory,
  onSettings,
}: MobileBottomNavProps) {
  return (
    <nav className="mobile-bottom-nav" aria-label="Quick actions">
      <button
        type="button"
        className={`mobile-bottom-nav__item${activeTab === "execute" ? " mobile-bottom-nav__item--active" : ""}`}
        onClick={() => { triggerHaptic(); onExecute(); }}
        aria-label="Execute trade"
        aria-current={activeTab === "execute" ? "page" : undefined}
      >
        <ExecuteIcon active={activeTab === "execute"} />
        <span className="mobile-bottom-nav__label">Execute</span>
      </button>

      <button
        type="button"
        className={`mobile-bottom-nav__item${activeTab === "history" ? " mobile-bottom-nav__item--active" : ""}`}
        onClick={() => { triggerHaptic(); onHistory(); }}
        aria-label="View trade history"
        aria-current={activeTab === "history" ? "page" : undefined}
      >
        <HistoryIcon active={activeTab === "history"} />
        <span className="mobile-bottom-nav__label">History</span>
      </button>

      <button
        type="button"
        className={`mobile-bottom-nav__item${activeTab === "settings" ? " mobile-bottom-nav__item--active" : ""}`}
        onClick={() => { triggerHaptic(); onSettings(); }}
        aria-label="Open settings"
        aria-current={activeTab === "settings" ? "page" : undefined}
      >
        <SettingsIcon active={activeTab === "settings"} />
        <span className="mobile-bottom-nav__label">Settings</span>
      </button>
    </nav>
  );
}
