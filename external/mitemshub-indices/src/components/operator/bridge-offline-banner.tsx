"use client";

import React, { useEffect, useState } from "react";

export type BridgeOfflineBannerProps = {
  /** Whether the bridge is currently detected as offline. */
  offline: boolean;
  /** Callback when the user clicks Retry. */
  onRetry?: () => void;
  /** Whether a retry is currently in progress. */
  retrying?: boolean;
  /** Auto-retry attempt number (1-based). 0 when not retrying. */
  autoRetryAttempt?: number;
  /** Seconds until the next auto-retry fires. 0 when not scheduled. */
  secondsUntilRetry?: number;
  /** Whether auto-retry is paused by the user. */
  autoRetryPaused?: boolean;
  /** Pause auto-retry. */
  onPauseAutoRetry?: () => void;
  /** Resume auto-retry. */
  onResumeAutoRetry?: () => void;
};

/**
 * Prominent red/orange banner shown at the top of the dashboard when the
 * Python backend bridge is not connected or unreachable.
 *
 * Features:
 * - High-contrast red/orange gradient with subtle pulse animation
 * - Animated pulsing dot for visual urgency
 * - Retry button with spinner state during retry
 * - Auto-dismisses with a slide-up transition when the bridge comes back online
 * - Accessible with role="alert" and aria-live
 */
export function BridgeOfflineBanner({
  offline,
  onRetry,
  retrying = false,
  autoRetryAttempt = 0,
  secondsUntilRetry = 0,
  autoRetryPaused = false,
  onPauseAutoRetry,
  onResumeAutoRetry,
}: BridgeOfflineBannerProps) {
  const [visible, setVisible] = useState(false);
  const [animatingOut, setAnimatingOut] = useState(false);

  useEffect(() => {
    if (offline) {
      // Mount with slide-in
      setAnimatingOut(false);
      setVisible(true);
    } else if (visible) {
      // Slide out, then unmount
      setAnimatingOut(true);
      const timer = setTimeout(() => {
        setVisible(false);
        setAnimatingOut(false);
      }, 350);
      return () => clearTimeout(timer);
    }
  }, [offline, visible]);

  if (!visible) return null;

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="bridge-offline-banner"
      style={{
        marginBottom: "0.75rem",
        borderRadius: "0.875rem",
        padding: "0.75rem 1rem",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "0.75rem",
        flexWrap: "wrap",
        background: "linear-gradient(135deg, rgba(196, 68, 58, 0.12), rgba(184, 134, 11, 0.10))",
        border: "1px solid rgba(196, 68, 58, 0.22)",
        boxShadow: "0 4px 16px rgba(196, 68, 58, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.6)",
        animation: animatingOut
          ? "bridgeBannerSlideUp 350ms var(--ease-out) forwards"
          : "bridgeBannerSlideDown 400ms var(--ease-out)",
        transition: "opacity 300ms ease, box-shadow 300ms ease",
      }}
    >
      {/* Left: icon + message */}
      <div className="flex items-center gap-2.5 min-w-0">
        {/* Pulsing warning dot */}
        <span
          className="bridge-offline-dot flex-shrink-0"
          aria-hidden="true"
          style={{
            width: "0.625rem",
            height: "0.625rem",
            borderRadius: "9999px",
            background: "var(--accent-danger, #c4443a)",
            boxShadow: "0 0 0 0 rgba(196, 68, 58, 0.35)",
            animation: "bridgeDotPulse 2s ease-in-out infinite",
          }}
        />
        <div className="min-w-0">
          <p
            className="text-sm font-semibold leading-tight"
            style={{ color: "var(--accent-danger, #c4443a)" }}
          >
            Bridge Offline
          </p>
          <p
            className="text-xs leading-snug mt-0.5"
            style={{ color: "var(--text-body, #475569)" }}
          >
            Intelligence panels will populate when the engine is running
          </p>
        </div>
      </div>

      {/* Right: auto-retry status + Retry button */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {/* Auto-retry countdown */}
        {autoRetryAttempt > 0 && !retrying && !autoRetryPaused && secondsUntilRetry > 0 && (
          <span
            className="text-[10px] font-medium tabular-nums"
            style={{ color: "var(--text-muted, #7c879a)" }}
            title={`Auto-retry attempt ${autoRetryAttempt} — next try in ${secondsUntilRetry}s`}
          >
            Retry in {secondsUntilRetry}s
          </span>
        )}
        {autoRetryAttempt > 0 && !retrying && autoRetryPaused && (
          <span
            className="text-[10px] font-medium"
            style={{ color: "var(--text-muted, #7c879a)" }}
          >
            Paused
          </span>
        )}

        {/* Pause/Resume button — only when auto-retry is active */}
        {autoRetryAttempt > 0 && !retrying && onPauseAutoRetry && onResumeAutoRetry && (
          <button
            type="button"
            onClick={autoRetryPaused ? onResumeAutoRetry : onPauseAutoRetry}
            className="rounded-md border px-2 py-1 text-[10px] font-medium transition-all active:scale-95"
            style={{
              borderColor: "rgba(196, 68, 58, 0.18)",
              background: "rgba(196, 68, 58, 0.04)",
              color: "var(--text-muted, #7c879a)",
            }}
            aria-label={autoRetryPaused ? "Resume auto-retry" : "Pause auto-retry"}
            title={autoRetryPaused ? "Resume automatic reconnection attempts" : "Pause automatic reconnection attempts"}
          >
            {autoRetryPaused ? (
              <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
            ) : (
              <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <rect x="6" y="4" width="4" height="16" />
                <rect x="14" y="4" width="4" height="16" />
              </svg>
            )}
          </button>
        )}

        {/* Manual Retry button */}
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            disabled={retrying}
            aria-label="Retry bridge connection"
            className="bridge-offline-retry-btn flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              borderColor: "rgba(196, 68, 58, 0.25)",
              background: "rgba(196, 68, 58, 0.08)",
              color: "var(--accent-danger, #c4443a)",
              whiteSpace: "nowrap",
            }}
          >
            {retrying ? (
              <>
                <span
                  className="inline-block w-3 h-3 rounded-full border-2 border-current border-t-transparent animate-spin"
                  aria-hidden="true"
                />
                Retrying…
              </>
            ) : (
              <>
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <polyline points="23 4 23 10 17 10" />
                  <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
                </svg>
                Retry
              </>
            )}
          </button>
        )}
      </div>

      <style jsx>{`
        .bridge-offline-retry-btn:hover:not(:disabled) {
          background: rgba(196, 68, 58, 0.14) !important;
          border-color: rgba(196, 68, 58, 0.35) !important;
          box-shadow: 0 2px 8px rgba(196, 68, 58, 0.1);
        }
      `}</style>

      <style jsx global>{`
        @keyframes bridgeBannerSlideDown {
          from {
            opacity: 0;
            transform: translateY(-12px);
            max-height: 0;
          }
          to {
            opacity: 1;
            transform: translateY(0);
            max-height: 120px;
          }
        }
        @keyframes bridgeBannerSlideUp {
          from {
            opacity: 1;
            transform: translateY(0);
            max-height: 120px;
          }
          to {
            opacity: 0;
            transform: translateY(-12px);
            max-height: 0;
          }
        }
        @keyframes bridgeDotPulse {
          0%,
          100% {
            box-shadow: 0 0 0 0 rgba(196, 68, 58, 0.35);
            transform: scale(1);
          }
          50% {
            box-shadow: 0 0 0 6px rgba(196, 68, 58, 0);
            transform: scale(1.15);
          }
        }
      `}</style>
    </div>
  );
}
