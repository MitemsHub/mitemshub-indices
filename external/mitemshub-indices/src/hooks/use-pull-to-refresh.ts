"use client";

import { useCallback, useRef, useState } from "react";

type PullToRefreshState = {
  /** Current pull distance in pixels (0 when idle). */
  pullDistance: number;
  /** True while the refresh callback is executing. */
  isRefreshing: boolean;
  /** True when the user has pulled past the trigger threshold. */
  isThresholdReached: boolean;
  /** The configured threshold for the current instance (for progress calculation). */
  threshold: number;
};

type UsePullToRefreshOptions = {
  /** Distance (px) the user must pull down to trigger a refresh. Default: 80. */
  threshold?: number;
  /** Maximum pull distance (px) with rubber-band cap. Default: 160. */
  maxPull?: number;
  /** Rubber-band factor (0–1). Higher = more resistance. Default: 0.5. */
  resistance?: number;
  /** Callback invoked when pull exceeds threshold and finger lifts. */
  onRefresh: () => void | Promise<void>;
  /** Guard: return false to suppress the gesture (e.g. already loading, desktop). */
  enabled?: boolean;
};

/**
 * Custom hook that turns a vertical pull-down gesture into a refresh trigger.
 *
 * Returns touch-event handlers to spread onto a scroll container and the
 * current pull state for rendering a visual indicator.
 *
 * Usage:
 * ```tsx
 * const { pullDistance, isRefreshing, isThresholdReached, handlers } =
 *   usePullToRefresh({ onRefresh: () => reload(), enabled: isMobile });
 *
 * <div {...handlers} style={{ paddingTop: pullDistance }}>
 *   {isRefreshing && <Spinner />}
 * </div>
 * ```
 */
export function usePullToRefresh({
  threshold = 80,
  maxPull = 160,
  resistance = 0.5,
  onRefresh,
  enabled = true,
}: UsePullToRefreshOptions) {
  const [state, setState] = useState<PullToRefreshState>({
    pullDistance: 0,
    isRefreshing: false,
    isThresholdReached: false,
    threshold,
  });

  const touchStartY = useRef(0);
  const currentPull = useRef(0);
  const isPulling = useRef(false);

  const resetPull = useCallback(() => {
    currentPull.current = 0;
    isPulling.current = false;
    setState((prev) => ({
      ...prev,
      pullDistance: 0,
      isThresholdReached: false,
    }));
  }, []);

  const handleTouchStart = useCallback(
    (e: React.TouchEvent) => {
      if (!enabled || state.isRefreshing) return;

      // Only activate when scrolled to the top (or very close)
      const scrollable = e.currentTarget as HTMLElement;
      if (scrollable.scrollTop > 5) return;

      touchStartY.current = e.touches[0].clientY;
      isPulling.current = true;
    },
    [enabled, state.isRefreshing],
  );

  const handleTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (!isPulling.current || !enabled || state.isRefreshing) return;

      const deltaY = e.touches[0].clientY - touchStartY.current;

      // Only allow downward pull (positive deltaY)
      if (deltaY <= 0) {
        resetPull();
        return;
      }

      // Rubber-band formula: diminishing returns as pull increases
      const pull = Math.min(deltaY * resistance, maxPull);
      currentPull.current = pull;

      setState({
        pullDistance: pull,
        isRefreshing: false,
        isThresholdReached: pull >= threshold,
        threshold,
      });
    },
    [enabled, state.isRefreshing, resistance, maxPull, threshold, resetPull],
  );

  const handleTouchEnd = useCallback(() => {
    if (!isPulling.current || !enabled) {
      resetPull();
      return;
    }

    if (currentPull.current >= threshold && !state.isRefreshing) {
      // Trigger refresh — keep the indicator visible at threshold height
      setState({
        pullDistance: threshold,
        isRefreshing: true,
        isThresholdReached: false,
        threshold,
      });

      // Fire the refresh callback
      const result = onRefresh();
      if (result && typeof (result as Promise<void>).then === "function") {
        (result as Promise<void>).finally(() => {
          resetPull();
        });
      } else {
        // Sync callback — reset after a brief delay for visual feedback
        setTimeout(resetPull, 800);
      }
    } else {
      resetPull();
    }
  }, [enabled, threshold, state.isRefreshing, onRefresh, resetPull]);

  return {
    pullDistance: state.pullDistance,
    isRefreshing: state.isRefreshing,
    isThresholdReached: state.isThresholdReached,
    threshold: state.threshold,
    handlers: {
      onTouchStart: handleTouchStart,
      onTouchMove: handleTouchMove,
      onTouchEnd: handleTouchEnd,
    } as React.HTMLAttributes<HTMLDivElement>,
  };
}
