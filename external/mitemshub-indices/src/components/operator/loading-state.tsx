import React from "react";

export function LoadingState() {
  return (
    <div
      className="loading-state mt-6 rounded-2xl p-5"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center gap-3">
        <span className="loading-pulse" aria-hidden="true" />
        <p className="utility-copy text-xs uppercase tracking-[0.24em]">
          Updating live plan
        </p>
      </div>
      <p className="mt-3 text-base text-[var(--text-strong)]">
        Fetching the latest local market reading and trade plan...
      </p>
    </div>
  );
}
