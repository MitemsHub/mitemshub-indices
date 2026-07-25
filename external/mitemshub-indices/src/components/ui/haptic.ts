"use client";

/**
 * Shared haptic feedback utility for mobile interactions.
 *
 * Uses the Vibration API (navigator.vibrate) which works on most Android
 * browsers and some iOS webviews. Desktop browsers silently no-op.
 *
 * All patterns are progressive enhancements — if vibrate is unavailable,
 * calls silently do nothing.
 *
 * Usage:
 * ```tsx
 * import { haptic } from "../ui/haptic";
 *
 * <button onClick={() => { haptic.tap(); doSomething(); }}>
 *   Click me
 * </button>
 * ```
 */

/** Check if the Vibration API is available. */
function canVibrate(): boolean {
  return typeof navigator !== "undefined" && "vibrate" in navigator;
}

/**
 * Light single tap — for tab switches, button presses, general interactions.
 * Duration: 10ms
 */
function tap(): void {
  if (canVibrate()) navigator.vibrate(10);
}

/**
 * Double buzz — for close/dismiss actions, destructive operations.
 * Pattern: 15ms → 50ms pause → 10ms
 */
function close(): void {
  if (canVibrate()) navigator.vibrate([15, 50, 10]);
}

/**
 * Single buzz — for drag-to-dismiss threshold crossing.
 * Duration: 10ms (same as tap, but semantically distinct)
 */
function dismiss(): void {
  if (canVibrate()) navigator.vibrate(10);
}

/**
 * Stronger pulse — for animation midpoints during dismiss gestures.
 * Simulates the sheet "clicking out of its rails".
 * Duration: 20ms
 */
function midpoint(): void {
  if (canVibrate()) navigator.vibrate(20);
}

/**
 * Success confirmation — for completed actions (trade executed, saved, etc.).
 * Pattern: short → pause → long → pause → short (triple pulse)
 */
function success(): void {
  if (canVibrate()) navigator.vibrate([8, 40, 12, 40, 8]);
}

/**
 * Error / warning — for failed actions, validation errors.
 * Pattern: two long buzzes
 */
function error(): void {
  if (canVibrate()) navigator.vibrate([30, 60, 30]);
}

/**
 * Double-tap — for the Execute button to differentiate from lighter taps.
 * Two quick pulses with a short gap between them.
 * Duration: [10, 50, 10]
 */
function doubleTap(): void {
  if (canVibrate()) navigator.vibrate([10, 50, 10]);
}

/** All haptic patterns organized by intent. */
export const haptic = {
  tap,
  doubleTap,
  close,
  dismiss,
  midpoint,
  success,
  error,
} as const;
