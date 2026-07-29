"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";

type NotificationPreferences = {
  newTradePlan: boolean;
  targetHit: boolean;
  stopHit: boolean;
  entryFilled: boolean;
  guardianUpdates: boolean;
};

type NotificationPermission = "granted" | "denied" | "default";

type NotificationBellProps = {
  permission: NotificationPermission;
  prefs: NotificationPreferences;
  isSupported: boolean;
  onEnable: () => Promise<boolean>;
  onTogglePref: (key: keyof NotificationPreferences) => void;
};

const PREF_LABELS: Record<keyof NotificationPreferences, { label: string; icon: string }> = {
  newTradePlan: { label: "New Trade Plan", icon: "📈" },
  targetHit: { label: "Target Hit", icon: "🎯" },
  stopHit: { label: "Stop Hit", icon: "🛑" },
  entryFilled: { label: "Entry Filled", icon: "✅" },
  guardianUpdates: { label: "Guardian Updates", icon: "🟢" },
};

export function NotificationBell({
  permission,
  prefs,
  isSupported,
  onEnable,
  onTogglePref,
}: NotificationBellProps) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const [dropdownPos, setDropdownPos] = useState({ top: 0, right: 16 });

  // Track mount state for portal
  useEffect(() => {
    setMounted(true);
  }, []);

  // Calculate dropdown position from button's bounding rect
  const updatePosition = useCallback(() => {
    if (!btnRef.current) return;
    const rect = btnRef.current.getBoundingClientRect();
    setDropdownPos({
      top: rect.bottom + 8,
      right: window.innerWidth - rect.right,
    });
  }, []);

  // Update position when opening and on scroll/resize
  useEffect(() => {
    if (!open) return;
    updatePosition();
    const onScroll = () => updatePosition();
    const onResize = () => updatePosition();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
    };
  }, [open, updatePosition]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      const clickedInsideBell = ref.current?.contains(e.target as Node);
      const clickedInsideDropdown = dropdownRef.current?.contains(e.target as Node);
      if (!clickedInsideBell && !clickedInsideDropdown) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  if (!isSupported) return null;

  const hasAnyEnabled = Object.values(prefs).some(Boolean);
  const bellColor =
    permission === "granted" && hasAnyEnabled
      ? "var(--accent-ink)"
      : "var(--text-muted)";

  const dropdown = (
    <div
      ref={dropdownRef}
      className="fixed z-[9999] w-72 rounded-2xl border border-[var(--line-subtle)] bg-[var(--bg-panel-strong)] shadow-[var(--shadow-elevated)] overflow-hidden"
      style={{ top: dropdownPos.top, right: dropdownPos.right }}
      role="menu"
    >
          {/* Header with title and close button */}
          <div className="flex items-center justify-between px-4 pt-4 pb-2">
            <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[var(--text-muted)]">
              Notifications
            </p>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="flex items-center justify-center w-6 h-6 rounded-full hover:bg-[var(--bg-surface-hover)] transition-colors"
              aria-label="Close notifications"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          <div className="px-4 pb-4">
            {permission !== "granted" && (
              <div className="mb-3 p-3 rounded-xl bg-[var(--accent-ink-soft)] border border-[var(--accent-ink-soft)]">
                <p className="text-sm text-[var(--accent-ink)] mb-2">
                  {permission === "denied"
                    ? "Notifications blocked by browser. Enable them in your browser settings."
                    : "Enable browser notifications to get alerts for trade events."}
                </p>
                {permission === "default" && (
                  <button
                    type="button"
                    onClick={async () => {
                      await onEnable();
                    }}
                    className="text-sm font-medium px-3 py-1.5 rounded-lg bg-[var(--accent-ink)] text-white hover:opacity-90 transition-opacity"
                  >
                    Allow Notifications
                  </button>
                )}
              </div>
            )}

            {permission === "granted" && (
              <div className="space-y-1">
                {(Object.keys(PREF_LABELS) as Array<keyof NotificationPreferences>).map(
                  (key) => {
                    const { label, icon } = PREF_LABELS[key];
                    return (
                      <label
                        key={key}
                        className="flex items-center justify-between gap-3 py-2 px-2 rounded-lg hover:bg-[var(--bg-surface-hover)] cursor-pointer transition-colors"
                      >
                        <span className="flex items-center gap-2.5 text-sm text-[var(--text-body)]">
                          <span className="text-base">{icon}</span>
                          {label}
                        </span>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={prefs[key]}
                          onClick={() => onTogglePref(key)}
                          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors duration-200 ${
                            prefs[key]
                              ? "bg-[var(--accent-positive)]"
                              : "bg-[var(--line-subtle)]"
                          }`}
                        >
                          <span
                            className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                              prefs[key] ? "translate-x-[18px]" : "translate-x-[3px]"
                            }`}
                          />
                        </button>
                      </label>
                    );
                  },
                )}
              </div>
            )}

            {permission === "granted" && !hasAnyEnabled && (
              <p className="mt-3 text-xs text-[var(--text-muted)] text-center">
                All notifications disabled. Toggle one above to enable.
              </p>
            )}
          </div>
        </div>
  );

  return (
    <div className="relative" ref={ref} suppressHydrationWarning>
      {/* Bell button */}
      <button
        ref={btnRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="relative flex items-center justify-center w-10 h-10 rounded-full transition-all duration-200 hover:bg-[var(--line-subtle)] active:scale-95"
        title="Notification settings"
        aria-label="Notification settings"
      >
        <svg
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke={bellColor}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {permission === "granted" && hasAnyEnabled && (
          <span className="absolute top-2 right-2 w-2.5 h-2.5 rounded-full bg-[var(--accent-positive)] ring-2 ring-[var(--bg-canvas)]" />
        )}
        {permission === "denied" && (
          <span className="absolute top-2 right-2 w-2.5 h-2.5 rounded-full bg-[var(--accent-danger)] ring-2 ring-[var(--bg-canvas)]" />
        )}
      </button>

      {/* Dropdown — portaled to document.body to escape .app-shell stacking context */}
      {mounted && open && createPortal(dropdown, document.body)}
    </div>
  );
}
