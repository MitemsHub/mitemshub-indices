import React from "react";

/**
 * A thin animated progress bar mounted between the command-rail and the
 * intelligence/decision stage during active analysis. Replaces the old
 * `LoadingState` card that was shown redundantly inside PrimaryCallPanel
 * while the shell's full-page `SkeletonLoader` was already visible.
 */
export function CommandBarLoadingStrip() {
  return (
    <div
      className="relative h-1 w-full overflow-hidden rounded-full bg-[var(--line-subtle)]"
      role="progressbar"
      aria-label="Analyzing market data"
      aria-busy="true"
    >
      <div
        className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-[var(--accent-ink)] via-[var(--accent-positive)] to-[var(--accent-ink)]"
        style={{
          width: "40%",
          animation: "commandBarStrip 1.8s ease-in-out infinite",
        }}
      />
      <style>{`
        @keyframes commandBarStrip {
          0%   { transform: translateX(-100%); }
          100% { transform: translateX(350%); }
        }
      `}</style>
    </div>
  );
}

export function SkeletonLoader() {
  return (
    <div className="mt-5 space-y-4" role="status" aria-label="Loading content">
      {/* Main skeleton card */}
      <div className="surface rounded-2xl p-5">
        <div className="skeleton h-4 w-1/4 rounded mb-3" />
        <div className="space-y-2.5">
          <div className="skeleton h-3 rounded w-3/4" />
          <div className="skeleton h-3 rounded w-1/2" />
          <div className="skeleton h-3 rounded w-2/3" />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <div className="skeleton h-20 rounded-xl" />
          <div className="skeleton h-20 rounded-xl" />
          <div className="skeleton h-20 rounded-xl" />
        </div>
      </div>

      {/* Secondary skeleton row */}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="surface rounded-2xl p-5">
          <div className="skeleton h-3 w-1/3 rounded mb-3" />
          <div className="skeleton h-2.5 rounded w-full mb-2" />
          <div className="skeleton h-2.5 rounded w-5/6" />
        </div>
        <div className="surface rounded-2xl p-5">
          <div className="skeleton h-3 w-1/3 rounded mb-3" />
          <div className="skeleton h-2.5 rounded w-full mb-2" />
          <div className="skeleton h-2.5 rounded w-5/6" />
        </div>
      </div>
    </div>
  );
}
