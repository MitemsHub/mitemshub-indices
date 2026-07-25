"use client";

import React, { useRef, useState, useEffect } from "react";
import type { IntelPanelId } from "../../lib/constants";
import {
  INTEL_PANELS,
  readIntelPanelOverrides,
  writeIntelPanelOverrides,
} from "../../lib/constants";

type IntelPanelTogglesProps = {
  tradingMode: string;
  enabledPanels: IntelPanelId[];
  onChange: (enabled: IntelPanelId[]) => void;
};

export function IntelPanelToggles({
  tradingMode,
  enabledPanels,
  onChange,
}: IntelPanelTogglesProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on click outside
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const togglePanel = (panelId: IntelPanelId) => {
    const next = enabledPanels.includes(panelId)
      ? enabledPanels.filter((id) => id !== panelId)
      : [...enabledPanels, panelId];
    onChange(next);

    // Persist to localStorage
    const overrides = readIntelPanelOverrides();
    overrides[tradingMode] = next;
    writeIntelPanelOverrides(overrides);
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 rounded-md border border-[var(--line-subtle)] bg-transparent px-2 py-1 text-[11px] font-medium text-[var(--text-muted)] hover:bg-[var(--bg-surface-hover)] hover:text-[var(--text-body)] active:scale-95 transition-all"
        aria-label="Toggle intelligence panels"
        aria-expanded={open}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
        Panels
        <span className="text-[10px] text-[var(--text-muted)] font-normal">
          ({enabledPanels.length}/{INTEL_PANELS.length})
        </span>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 z-50 w-72 rounded-xl border border-[var(--line-subtle)] bg-[var(--bg-panel-strong)] shadow-[var(--shadow-elevated)] backdrop-blur-xl p-2">
          <div className="px-2 py-1.5 border-b border-[var(--line-subtle)] mb-1">
            <p className="text-[11px] font-medium text-[var(--text-strong)]">
              Intelligence Panels
            </p>
            <p className="text-[10px] text-[var(--text-muted)] mt-0.5">
              Visible panels for &quot;{tradingMode.replace("_", " ")}&quot; mode
            </p>
          </div>
          <div className="space-y-0.5">
            {INTEL_PANELS.map((panel) => {
              const isOn = enabledPanels.includes(panel.id);
              return (
                <button
                  key={panel.id}
                  type="button"
                  onClick={() => togglePanel(panel.id)}
                  className={`flex items-start gap-2.5 w-full rounded-lg px-2 py-2 text-left transition-all ${
                    isOn
                      ? "bg-[var(--accent-ink-soft)]"
                      : "hover:bg-[var(--bg-surface-hover)] opacity-55"
                  }`}
                  aria-pressed={isOn}
                >
                  <span
                    className={`mt-0.5 flex-shrink-0 w-4 h-4 rounded border-2 flex items-center justify-center transition-all ${
                      isOn
                        ? "border-[var(--accent-ink)] bg-[var(--accent-ink)]"
                        : "border-[var(--line-strong)]"
                    }`}
                  >
                    {isOn && (
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    )}
                  </span>
                  <div className="min-w-0">
                    <p className={`text-[12px] font-medium leading-snug ${
                      isOn ? "text-[var(--text-strong)]" : "text-[var(--text-muted)]"
                    }`}>
                      {panel.label}
                    </p>
                    <p className="text-[10px] text-[var(--text-muted)] leading-snug mt-0.5 line-clamp-2">
                      {panel.description}
                    </p>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
