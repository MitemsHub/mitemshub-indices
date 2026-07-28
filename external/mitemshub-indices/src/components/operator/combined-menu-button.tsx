"use client";

import React, { useState, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";

type NotificationPreferences = {
  newTradePlan: boolean;
  targetHit: boolean;
  stopHit: boolean;
  entryFilled: boolean;
  guardianUpdates: boolean;
};

const PREF_LABELS: Record<keyof NotificationPreferences, { label: string; icon: string }> = {
  newTradePlan: { label: "New Trade Plan", icon: "📈" },
  targetHit: { label: "Target Hit", icon: "🎯" },
  stopHit: { label: "Stop Hit", icon: "🛑" },
  entryFilled: { label: "Entry Filled", icon: "✅" },
  guardianUpdates: { label: "Guardian Updates", icon: "🟢" },
};

type CombinedMenuButtonProps = {
  onOpenSettings: () => void;
  notificationPermission: "granted" | "denied" | "default";
  notificationPrefs: NotificationPreferences;
  onEnableNotifications: () => Promise<boolean>;
  onToggleNotificationPref: (key: keyof NotificationPreferences) => void;
  onToggleTheme: () => void;
  currentTheme: string;
};

function MenuIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function ChevronRightIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

function BackArrowIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 19 5 12 12 5" />
    </svg>
  );
}

type DrawerView = "menu" | "notifications";

export function CombinedMenuButton({
  onOpenSettings,
  notificationPermission,
  notificationPrefs,
  onEnableNotifications,
  onToggleNotificationPref,
  onToggleTheme,
  currentTheme,
}: CombinedMenuButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [view, setView] = useState<DrawerView>("menu");

  useEffect(() => {
    setMounted(true);
  }, []);

  // Reset view when drawer closes
  useEffect(() => {
    if (!isOpen) {
      const timer = setTimeout(() => setView("menu"), 300);
      return () => clearTimeout(timer);
    }
  }, [isOpen]);

  // Prevent body scroll when drawer is open
  useEffect(() => {
    if (!isOpen) return;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false);
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [isOpen]);

  const hasAnyEnabled = Object.values(notificationPrefs).some(Boolean);
  const bellColor =
    notificationPermission === "granted" && hasAnyEnabled
      ? "var(--accent-ink)"
      : "var(--text-muted)";

  const openDrawer = useCallback(() => {
    setIsOpen(true);
    setView("menu");
  }, []);

  const closeDrawer = useCallback(() => {
    setIsOpen(false);
  }, []);

  const menuSections = [
    {
      id: "settings",
      label: "Settings",
      subtitle: "Account, strategy & execution",
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      ),
      onClick: () => {
        closeDrawer();
        // Delay settings drawer until menu drawer animation completes
        setTimeout(() => onOpenSettings(), 350);
      },
    },
    {
      id: "notifications",
      label: "Notifications",
      subtitle: hasAnyEnabled ? "Manage alerts" : "All disabled",
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={bellColor} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
      ),
      badge: notificationPermission === "granted" && hasAnyEnabled,
      onClick: () => setView("notifications"),
    },
    {
      id: "theme",
      label: currentTheme === "dark" ? "Light Mode" : "Dark Mode",
      subtitle: `Currently ${currentTheme === "dark" ? "dark" : "light"}`,
      icon: (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          {currentTheme === "dark" ? (
            <>
              <circle cx="12" cy="12" r="5" />
              <line x1="12" y1="1" x2="12" y2="3" />
              <line x1="12" y1="21" x2="12" y2="23" />
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
              <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
              <line x1="1" y1="12" x2="3" y2="12" />
              <line x1="21" y1="12" x2="23" y2="12" />
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
              <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
            </>
          ) : (
            <>
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
            </>
          )}
        </svg>
      ),
      onClick: () => {
        onToggleTheme();
      },
    },
  ];

  const drawerContent = (
    <div className="combined-drawer-root">
      {/* Backdrop */}
      <div
        className={`combined-drawer-backdrop ${isOpen ? "combined-drawer-backdrop--open" : ""}`}
        onClick={closeDrawer}
        aria-hidden="true"
      />

      {/* Drawer panel */}
      <aside
        className={`combined-drawer-panel ${isOpen ? "combined-drawer-panel--open" : ""}`}
        role="dialog"
        aria-modal={isOpen ? "true" : undefined}
        aria-label="Menu"
      >
        {/* Header */}
        <div className="combined-drawer-header">
          {view === "menu" ? (
            <button
              type="button"
              onClick={closeDrawer}
              className="combined-drawer-close"
              aria-label="Close menu"
            >
              <CloseIcon />
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setView("menu")}
              className="combined-drawer-close"
              aria-label="Back to menu"
            >
              <BackArrowIcon />
            </button>
          )}
          <h2 className="combined-drawer-title">
            {view === "menu" ? "Menu" : "Notifications"}
          </h2>
          {view === "menu" ? (
            <div className="combined-drawer-spacer" />
          ) : (
            <button
              type="button"
              onClick={closeDrawer}
              className="combined-drawer-close"
              aria-label="Close menu"
            >
              <CloseIcon />
            </button>
          )}
        </div>

        {/* Content */}
        <div className="combined-drawer-content">
          {view === "menu" ? (
            /* Main menu sections */
            <div className="combined-drawer-sections">
              {menuSections.map((section, index) => (
                <button
                  key={section.id}
                  type="button"
                  onClick={section.onClick}
                  className="combined-drawer-section"
                  style={{ animationDelay: `${index * 60}ms` }}
                >
                  <div className="combined-drawer-section-icon">
                    {section.icon}
                  </div>
                  <div className="combined-drawer-section-text">
                    <span className="combined-drawer-section-label">{section.label}</span>
                    <span className="combined-drawer-section-subtitle">{section.subtitle}</span>
                  </div>
                  {section.badge && (
                    <span className="combined-drawer-section-badge" />
                  )}
                  <ChevronRightIcon />
                </button>
              ))}
            </div>
          ) : (
            /* Notification preferences */
            <div className="combined-drawer-notifications">
              {notificationPermission !== "granted" && (
                <div className="combined-drawer-notice">
                  <p className="combined-drawer-notice-text">
                    {notificationPermission === "denied"
                      ? "Notifications blocked by browser. Enable them in your browser settings."
                      : "Enable browser notifications to get alerts for trade events."}
                  </p>
                  {notificationPermission === "default" && (
                    <button
                      type="button"
                      onClick={onEnableNotifications}
                      className="combined-drawer-notice-btn"
                    >
                      Allow Notifications
                    </button>
                  )}
                </div>
              )}

              {notificationPermission === "granted" && (
                <div className="combined-drawer-prefs">
                  {(Object.keys(PREF_LABELS) as Array<keyof NotificationPreferences>).map(
                    (key, index) => {
                      const { label, icon } = PREF_LABELS[key];
                      return (
                        <label
                          key={key}
                          className="combined-drawer-pref"
                          style={{ animationDelay: `${index * 50}ms` }}
                        >
                          <span className="combined-drawer-pref-icon">{icon}</span>
                          <span className="combined-drawer-pref-label">{label}</span>
                          <button
                            type="button"
                            role="switch"
                            aria-checked={notificationPrefs[key]}
                            onClick={() => onToggleNotificationPref(key)}
                            className={`combined-drawer-switch ${notificationPrefs[key] ? "combined-drawer-switch--on" : ""}`}
                          >
                            <span className={`combined-drawer-switch-thumb ${notificationPrefs[key] ? "combined-drawer-switch-thumb--on" : ""}`} />
                          </button>
                        </label>
                      );
                    },
                  )}
                </div>
              )}

              {notificationPermission === "granted" && !hasAnyEnabled && (
                <p className="combined-drawer-empty">
                  All notifications disabled. Toggle one above to enable.
                </p>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  );

  return (
    <>
      <button
        type="button"
        onClick={isOpen ? closeDrawer : openDrawer}
        className={`combined-menu-trigger ${isOpen ? "combined-menu-trigger--active" : ""}`}
        aria-label={isOpen ? "Close menu" : "Open menu"}
        aria-expanded={isOpen}
      >
        {isOpen ? <CloseIcon /> : <MenuIcon />}
      </button>

      {mounted && createPortal(drawerContent, document.body)}

      <style jsx global>{`
        .combined-menu-trigger {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 40px;
          height: 40px;
          border-radius: 12px;
          border: 1px solid var(--line-subtle);
          background: var(--bg-panel);
          color: var(--text-body);
          cursor: pointer;
          transition: all 200ms var(--ease-out);
          position: relative;
          z-index: 41;
        }

        .combined-menu-trigger:hover {
          background: var(--bg-panel-strong);
          color: var(--text-strong);
          border-color: var(--line-strong);
        }

        .combined-menu-trigger:active {
          transform: scale(0.95);
        }

        .combined-menu-trigger--active {
          background: var(--accent-ink);
          color: white;
          border-color: var(--accent-ink);
        }

        /* ── Drawer root ─────────────────────────────────────────── */
        .combined-drawer-root {
          position: fixed;
          inset: 0;
          z-index: 9999;
          pointer-events: none;
        }

        .combined-drawer-root > * {
          pointer-events: auto;
        }

        /* ── Backdrop ────────────────────────────────────────────── */
        .combined-drawer-backdrop {
          position: fixed;
          inset: 0;
          background: rgba(15, 18, 23, 0.5);
          backdrop-filter: blur(4px);
          opacity: 0;
          pointer-events: none;
          transition: opacity 300ms var(--ease-out);
          z-index: 0;
        }

        .combined-drawer-backdrop--open {
          opacity: 1;
          pointer-events: auto;
        }

        /* ── Panel ───────────────────────────────────────────────── */
        .combined-drawer-panel {
          position: fixed;
          top: 0;
          right: 0;
          bottom: 0;
          width: min(22rem, 85vw);
          background: var(--bg-panel-strong);
          border-left: 1px solid var(--line-subtle);
          box-shadow: var(--shadow-elevated);
          transform: translateX(100%);
          transition: transform 350ms var(--ease-bounce);
          z-index: 1;
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }

        .combined-drawer-panel--open {
          transform: translateX(0);
        }

        /* ── Header ──────────────────────────────────────────────── */
        .combined-drawer-header {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 16px 20px;
          border-bottom: 1px solid var(--line-subtle);
          flex-shrink: 0;
        }

        .combined-drawer-close {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 36px;
          height: 36px;
          border-radius: 10px;
          border: 1px solid var(--line-subtle);
          background: var(--bg-panel);
          color: var(--text-body);
          cursor: pointer;
          transition: all 150ms var(--ease-out);
          flex-shrink: 0;
        }

        .combined-drawer-close:hover {
          background: var(--bg-surface-hover);
          color: var(--text-strong);
          border-color: var(--line-strong);
        }

        .combined-drawer-title {
          flex: 1;
          font-size: 1rem;
          font-weight: 600;
          color: var(--text-strong);
          margin: 0;
          font-family: "Inter", "Segoe UI", system-ui, sans-serif;
        }

        .combined-drawer-spacer {
          width: 36px;
          flex-shrink: 0;
        }

        /* ── Content ─────────────────────────────────────────────── */
        .combined-drawer-content {
          flex: 1;
          overflow-y: auto;
          padding: 12px;
        }

        /* ── Menu sections ───────────────────────────────────────── */
        .combined-drawer-sections {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .combined-drawer-section {
          display: flex;
          align-items: center;
          gap: 14px;
          width: 100%;
          padding: 14px 16px;
          border-radius: 14px;
          border: 1px solid transparent;
          background: transparent;
          color: var(--text-body);
          cursor: pointer;
          transition: all 180ms var(--ease-out);
          text-align: left;
          animation: drawerItemSlideIn 250ms var(--ease-out) backwards;
        }

        .combined-drawer-section:hover {
          background: var(--bg-surface-hover);
          border-color: var(--line-subtle);
          color: var(--text-strong);
        }

        .combined-drawer-section:active {
          transform: scale(0.98);
        }

        .combined-drawer-section-icon {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 44px;
          height: 44px;
          border-radius: 12px;
          background: var(--bg-panel-muted);
          color: var(--text-body);
          flex-shrink: 0;
          transition: all 180ms var(--ease-out);
        }

        .combined-drawer-section:hover .combined-drawer-section-icon {
          background: var(--accent-ink-soft);
          color: var(--accent-ink);
        }

        .combined-drawer-section-text {
          flex: 1;
          display: flex;
          flex-direction: column;
          gap: 2px;
          min-width: 0;
        }

        .combined-drawer-section-label {
          font-size: 15px;
          font-weight: 600;
          color: var(--text-strong);
          line-height: 1.3;
        }

        .combined-drawer-section-subtitle {
          font-size: 12px;
          color: var(--text-muted);
          line-height: 1.3;
        }

        .combined-drawer-section-badge {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--accent-positive);
          flex-shrink: 0;
        }

        .combined-drawer-section > svg:last-child {
          color: var(--text-muted);
          flex-shrink: 0;
          opacity: 0.5;
        }

        .combined-drawer-section:hover > svg:last-child {
          opacity: 1;
          color: var(--accent-ink);
        }

        /* ── Notifications ───────────────────────────────────────── */
        .combined-drawer-notifications {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .combined-drawer-notice {
          padding: 16px;
          border-radius: 14px;
          background: var(--accent-ink-soft);
          border: 1px solid rgba(31, 75, 153, 0.15);
        }

        .combined-drawer-notice-text {
          font-size: 13px;
          color: var(--accent-ink);
          margin: 0 0 12px;
          line-height: 1.5;
        }

        .combined-drawer-notice-btn {
          display: inline-flex;
          align-items: center;
          padding: 8px 16px;
          border-radius: 8px;
          border: none;
          background: var(--accent-ink);
          color: white;
          font-size: 13px;
          font-weight: 600;
          cursor: pointer;
          transition: opacity 150ms;
        }

        .combined-drawer-notice-btn:hover {
          opacity: 0.9;
        }

        .combined-drawer-prefs {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .combined-drawer-pref {
          display: flex;
          align-items: center;
          gap: 14px;
          padding: 14px 16px;
          border-radius: 12px;
          cursor: pointer;
          transition: background 150ms var(--ease-out);
          animation: drawerItemSlideIn 200ms var(--ease-out) backwards;
        }

        .combined-drawer-pref:hover {
          background: var(--bg-surface-hover);
        }

        .combined-drawer-pref-icon {
          font-size: 20px;
          width: 36px;
          height: 36px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 10px;
          background: var(--bg-panel-muted);
          flex-shrink: 0;
        }

        .combined-drawer-pref-label {
          flex: 1;
          font-size: 15px;
          font-weight: 500;
          color: var(--text-strong);
        }

        .combined-drawer-switch {
          position: relative;
          width: 44px;
          height: 24px;
          border-radius: 12px;
          border: none;
          background: var(--line-subtle);
          cursor: pointer;
          transition: background 200ms var(--ease-out);
          flex-shrink: 0;
        }

        .combined-drawer-switch--on {
          background: var(--accent-positive);
        }

        .combined-drawer-switch-thumb {
          position: absolute;
          top: 2px;
          left: 2px;
          width: 20px;
          height: 20px;
          border-radius: 10px;
          background: white;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
          transition: transform 200ms var(--ease-out);
        }

        .combined-drawer-switch-thumb--on {
          transform: translateX(20px);
        }

        .combined-drawer-empty {
          text-align: center;
          padding: 24px 16px;
          font-size: 13px;
          color: var(--text-muted);
          margin: 0;
        }

        /* ── Animations ──────────────────────────────────────────── */
        @keyframes drawerItemSlideIn {
          from {
            opacity: 0;
            transform: translateX(16px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }
      `}</style>
    </>
  );
}
