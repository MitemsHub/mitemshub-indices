"use client";

import React, { type ReactNode } from "react";

import { TABS, type IntelTab } from "../../lib/constants";

type IntelAccordionProps = {
  open: boolean;
  activeTab: IntelTab;
  onToggle: (open: boolean) => void;
  onTabChange: (tab: IntelTab) => void;
  /** Render the tab content — called with the active tab ID */
  renderContent: (tab: IntelTab) => ReactNode;
};

export function IntelAccordion({
  open,
  activeTab,
  onToggle,
  onTabChange,
  renderContent,
}: IntelAccordionProps) {
  return (
    <details
      className="intel-accordion mt-4 md:hidden"
      open={open}
      onToggle={(e) => onToggle(e.currentTarget.open)}
    >
      <summary className="flex items-center justify-between border-b border-[var(--line-subtle)] pb-2">
        <span className="text-sm font-medium text-[var(--text-strong)]">
          Intelligence {activeTab.charAt(0).toUpperCase() + activeTab.slice(1)}
        </span>
      </summary>
      <div className="mt-4 space-y-4">
        {/* Mobile tab bar inside accordion */}
        <div className="flex items-center gap-1 flex-wrap">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => onTabChange(tab.id)}
              className={`tab-button text-xs ${activeTab === tab.id ? "tab-button--active" : ""}`}
              aria-pressed={activeTab === tab.id}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {renderContent(activeTab)}
      </div>
    </details>
  );
}
