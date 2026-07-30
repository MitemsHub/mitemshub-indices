"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type AutoRetryState = {
  /** Whether auto-retry is currently active. */
  isRetrying: boolean;
  /** Current attempt number (1-based). Resets to 0 when offline ends. */
  attempt: number;
  /** Timestamp of the next scheduled retry (ms since epoch). 0 when not scheduled. */
  nextRetryAt: number;
  /** Seconds until the next retry fires. Updated every second. */
  secondsUntilRetry: number;
  /** Whether auto-retry is paused by the user. */
  paused: boolean;
};

type UseBridgeAutoRetryOptions = {
  /** Whether the bridge is currently detected as offline. */
  offline: boolean;
  /** Whether a manual or auto retry is currently in flight. */
  loading: boolean;
  /** The retry callback — typically `() => workspace.runSymbol(symbol)`. */
  onRetry: () => void;
  /** Base delay in ms before the first retry. Default: 30000 (30s). */
  baseDelayMs?: number;
  /** Maximum delay in ms between retries. Default: 300000 (5 min). */
  maxDelayMs?: number;
  /** Maximum number of attempts before pausing. 0 = unlimited. Default: 0. */
  maxAttempts?: number;
};

/**
 * Auto-retries bridge reconnection when the bridge goes offline.
 *
 * Uses exponential backoff: 30s → 60s → 120s → 240s → 300s (capped).
 * Resets the backoff when the bridge comes back online.
 * Pauses when the user manually clicks Retry (resumes if still offline).
 */
export function useBridgeAutoRetry({
  offline,
  loading,
  onRetry,
  baseDelayMs = 30_000,
  maxDelayMs = 300_000,
  maxAttempts = 0,
}: UseBridgeAutoRetryOptions): AutoRetryState & {
  pause: () => void;
  resume: () => void;
} {
  const [attempt, setAttempt] = useState(0);
  const [nextRetryAt, setNextRetryAt] = useState(0);
  const [secondsUntilRetry, setSecondsUntilRetry] = useState(0);
  const [paused, setPaused] = useState(false);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const attemptRef = useRef(0);
  const pausedRef = useRef(false);
  const offlineRef = useRef(offline);
  const loadingRef = useRef(loading);
  const onRetryRef = useRef(onRetry);

  // Keep refs in sync — avoids stale closures in setTimeout callbacks
  offlineRef.current = offline;
  loadingRef.current = loading;
  onRetryRef.current = onRetry;

  const clearTimers = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
    setNextRetryAt(0);
    setSecondsUntilRetry(0);
  }, []);

  const scheduleRetry = useCallback(
    (delayMs: number) => {
      clearTimers();
      const target = Date.now() + delayMs;
      setNextRetryAt(target);
      setSecondsUntilRetry(Math.ceil(delayMs / 1000));

      // Tick every second to update the countdown
      tickRef.current = setInterval(() => {
        const remaining = Math.max(0, Math.ceil((target - Date.now()) / 1000));
        setSecondsUntilRetry(remaining);
        if (remaining <= 0 && tickRef.current) {
          clearInterval(tickRef.current);
          tickRef.current = null;
        }
      }, 1000);

      timerRef.current = setTimeout(() => {
        clearTimers();
        if (!offlineRef.current || pausedRef.current || loadingRef.current) {
          return;
        }
        const nextAttempt = attemptRef.current + 1;
        attemptRef.current = nextAttempt;
        setAttempt(nextAttempt);
        onRetryRef.current();

        // Schedule next retry with exponential backoff
        const nextDelay = Math.min(baseDelayMs * Math.pow(2, nextAttempt - 1), maxDelayMs);
        scheduleRetry(nextDelay);
      }, delayMs);
    },
    [clearTimers, onRetry, baseDelayMs, maxDelayMs],
  );

  // Start auto-retry when bridge goes offline
  useEffect(() => {
    if (offline && !loading && !pausedRef.current) {
      // Start with the base delay
      if (attemptRef.current === 0) {
        attemptRef.current = 1;
        setAttempt(1);
      }
      const nextDelay = Math.min(
        baseDelayMs * Math.pow(2, Math.max(0, attemptRef.current - 1)),
        maxDelayMs,
      );
      scheduleRetry(nextDelay);
    } else if (!offline) {
      // Bridge came back online — reset everything
      clearTimers();
      attemptRef.current = 0;
      setAttempt(0);
      setPaused(false);
      pausedRef.current = false;
    } else if (loading) {
      // Retry in progress — clear the schedule (will reschedule after loading ends)
      clearTimers();
    }

    return clearTimers;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offline, loading, paused]);

  const pause = useCallback(() => {
    setPaused(true);
    pausedRef.current = true;
    clearTimers();
  }, [clearTimers]);

  const resume = useCallback(() => {
    setPaused(false);
    pausedRef.current = false;
    if (offlineRef.current && !loadingRef.current) {
      // Resume with base delay
      const nextDelay = baseDelayMs;
      scheduleRetry(nextDelay);
    }
  }, [baseDelayMs, scheduleRetry]);

  return {
    isRetrying: offline && !loading && attempt > 0 && !paused,
    attempt,
    nextRetryAt,
    secondsUntilRetry,
    paused,
    pause,
    resume,
  };
}
