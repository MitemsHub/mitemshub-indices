"use client";

import { useState, useRef, useEffect } from "react";

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
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  if (!isSupported) return null;

  const hasAnyEnabled = Object.values(prefs).some(Boolean);
  const bellColor =
    permission === "granted" && hasAnyEnabled
      ? "var(--accent-ink)"
      : "var(--text-muted)";

  return (
    <div className="relative" ref={ref}>
      {/* Bell button */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="relative flex items-center justify-center w-9 h-9 rounded-xl transition-all duration-180 hover:bg-[var(--bg-surface-hover)]"
        title="Notification settings"
        aria-label="Notification settings"
      >
        <svg
          width="18"
          height="18"
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
          <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-[var(--accent-positive)]" />
        )}
        {permission === "denied" && (
          <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-[var(--accent-danger)]" />
        )}
      </button>

      {/* Dropdown */}
      {open && (
        <div
          className="absolute right-0 top-full mt-2 z-50 w-72 rounded-2xl border border-[var(--line-subtle)] bg-[var(--bg-panel-strong)] shadow-[var(--shadow-elevated)] p-4"
          role="menu"
        >
          <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[var(--text-muted)] mb-3">
            Notifications
          </p>

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
      )}
    </div>
  );
}
