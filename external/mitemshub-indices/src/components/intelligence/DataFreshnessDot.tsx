"use client";

/**
 * Small green/gray dot indicating data freshness for intelligence panels.
 *
 * - Green pulsing dot: data is live and available
 * - Gray dot: data is stale, unavailable, or panel is loading
 */
export function DataFreshnessDot({ live }: { live: boolean }) {
  return (
    <span
      className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${
        live
          ? "bg-[var(--accent-positive)] shadow-[0_0_4px_rgba(15,107,87,0.4)]"
          : "bg-[var(--text-muted)] opacity-50"
      }`}
      aria-label={live ? "Data is live" : "Data unavailable"}
      title={live ? "Live data" : "No data available"}
    />
  );
}
