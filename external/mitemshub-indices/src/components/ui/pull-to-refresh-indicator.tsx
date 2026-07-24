"use client";

import React from "react";

type PullToRefreshIndicatorProps = {
  /** Current pull distance in pixels. */
  pullDistance: number;
  /** True while the refresh callback is executing. */
  isRefreshing: boolean;
  /** True when the user has pulled past the trigger threshold. */
  isThresholdReached: boolean;
  /** The configured pull threshold for progress calculation. */
  threshold?: number;
};

/**
 * Visual indicator for the pull-to-refresh gesture.
 *
 * Renders a small spinner + text that appears when the user pulls down
 * on mobile. The indicator slides down from the top with a smooth
 * spring-like animation and shows different states:
 * - Pulling: "Pull to refresh" with a downward arrow
 * - Threshold reached: "Release to refresh" with an upward arrow
 * - Refreshing: spinning loader with "Refreshing…"
 */
export function PullToRefreshIndicator({
  pullDistance,
  isRefreshing,
  isThresholdReached,
  threshold = 80,
}: PullToRefreshIndicatorProps) {
  const isVisible = pullDistance > 0 || isRefreshing;
  if (!isVisible) return null;

  const progress = Math.min(pullDistance / threshold, 1);

  return (
    <div
      className="pull-to-refresh"
      style={{
        height: isRefreshing ? 56 : pullDistance,
        opacity: isRefreshing ? 1 : Math.min(progress * 1.5, 1),
      }}
      aria-live="polite"
      aria-busy={isRefreshing}
      aria-hidden={pullDistance === 0 && !isRefreshing}
    >
      <div className="pull-to-refresh__content">
        {isRefreshing ? (
          <>
            <svg
              className="pull-to-refresh__spinner"
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--accent-ink)"
              strokeWidth="2.5"
              strokeLinecap="round"
            >
              <path d="M21 12a9 9 0 1 1-6.219-8.56" />
            </svg>
            <span className="pull-to-refresh__text">Refreshing…</span>
          </>
        ) : isThresholdReached ? (
          <>
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--accent-ink)"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="18 15 12 9 6 15" />
            </svg>
            <span className="pull-to-refresh__text">Release to refresh</span>
          </>
        ) : (
          <>
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--text-muted)"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
            <span className="pull-to-refresh__text">Pull to refresh</span>
          </>
        )}
      </div>
    </div>
  );
}
