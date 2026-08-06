"use client";

import React, { useEffect, useRef, useState } from "react";
import { XIcon } from "../../lib/icons";
import { useScrollLock } from "../../hooks/use-scroll-lock";
import type { FreshCallResponse, GuardianStatus, ExecutionMode, TrackedPosition } from "../../lib/contracts";
import { TradeInstructionPanel } from "./trade-instruction-panel";
import { haptic } from "../ui/haptic";

/** Minimum downward drag before the sheet auto-dismisses. */
const SNAP_THRESHOLD = 120;
/** How much resistance (0-1). 0.5 = drag half as far as your finger moves. */
const DRAG_RESISTANCE = 0.45;

type MobileTradeSheetProps = {
  open: boolean;
  call: FreshCallResponse | null;
  guardianStatus: GuardianStatus | null;
  trackedPosition: TrackedPosition | null;
  executing: boolean;
  executionMode: ExecutionMode;
  provenOnly?: boolean;
  onSubmitTrade: () => void;
  onCloseTrade: () => void;
  onSetExecutionMode: (mode: ExecutionMode) => void;
  onSetProvenOnly?: (value: boolean) => void;
  onClose: () => void;
};



export function MobileTradeSheet({
  open,
  call,
  guardianStatus,
  trackedPosition,
  executing,
  executionMode,
  provenOnly = false,
  onSubmitTrade,
  onCloseTrade,
  onSetExecutionMode,
  onSetProvenOnly = () => {},
  onClose,
}: MobileTradeSheetProps) {
  const sheetRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const dragStartYRef = useRef(0);
  const currentDragYRef = useRef(0);
  const scrollTopAtStartRef = useRef(0);
  const dragStartTimeRef = useRef(0);
  const dismissHapticTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [dragY, setDragY] = useState(0);
  const [atBottom, setAtBottom] = useState(false);
  const [exitDuration, setExitDuration] = useState<number | null>(null);

  // ── Scroll-end gradient hint ────────────────────────────────
  // Tracks whether the body content is scrolled to the bottom.
  // When not at bottom, a subtle fade-to-transparent gradient at
  // the lower edge hints that more content is available.
  const checkScrollBottom = () => {
    const el = bodyRef.current;
    if (!el) return;
    const threshold = 4; // px from bottom to consider "at bottom"
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight <= threshold);
  };

  useEffect(() => {
    if (!open) return;
    // Check after the sheet mounts and content renders
    requestAnimationFrame(() => checkScrollBottom());
  }, [open]);

  // Reset drag state when the sheet closes so the next open cycle starts clean.
  useEffect(() => {
    if (open) {
      // Opening: clear any leftover exit duration override from a previous
      // dismiss so the entry transition always uses the CSS-class default.
      setExitDuration(null);
      // Also cancel any pending midpoint haptic from a previous dismiss.
      if (dismissHapticTimerRef.current !== null) {
        clearTimeout(dismissHapticTimerRef.current);
        dismissHapticTimerRef.current = null;
      }
    } else if (exitDuration !== null) {
      // Closing: keep the inline transitionDuration override for the exit
      // animation, then clean it up after it finishes.
      const timer = setTimeout(() => setExitDuration(null), exitDuration + 50);
      return () => clearTimeout(timer);
    }
  }, [open, exitDuration]);

  // Close on Escape — with a double-buzz tactile signature distinct from drag-dismiss.
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        haptic.close();
        onClose();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  // Prevent body scroll when open
  useScrollLock(open);

  // ── Swipe-to-dismiss gesture handlers ───────────────────────
  // Drag anywhere on the sheet; if content is scrolled past top,
  // the gesture scrolls the content instead of dragging the sheet.

  const handleTouchStart = (e: React.TouchEvent) => {
    if (e.touches.length !== 1) return;
    dragStartYRef.current = e.touches[0].clientY;
    currentDragYRef.current = 0;
    scrollTopAtStartRef.current = bodyRef.current?.scrollTop ?? 0;
    dragStartTimeRef.current = Date.now();
    setIsDragging(true);
    setDragY(0);
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    if (e.touches.length !== 1) return;

    // If the body content is scrolled past top, let the browser
    // handle the gesture natively (scroll the content).
    if (scrollTopAtStartRef.current > 0) {
      return;
    }

    const deltaY = e.touches[0].clientY - dragStartYRef.current;
    if (deltaY <= 0) return; // Only allow downward drag

    // Prevent the browser from overscrolling/bouncing the page behind
    // the sheet when the user drags down at scrollTop === 0.
    e.preventDefault();

    // Apply dynamic resistance: the further you pull, the heavier it feels
    const resisted = Math.min(deltaY * DRAG_RESISTANCE, window.innerHeight * 0.5);
    currentDragYRef.current = resisted;
    setDragY(resisted);
  };

  const handleTouchEnd = () => {
    if (!isDragging) return;
    setIsDragging(false);

    if (currentDragYRef.current >= SNAP_THRESHOLD) {
      haptic.dismiss();

      // Compute average drag velocity (px/ms) over the entire gesture and
      // scale the dismiss animation duration: fast flick → 200ms, slow drag
      // → 400ms.  SNAP_THRESHOLD / velocity is the time (ms) it would take
      // to drag to the threshold at the current pace — a natural duration.
      const totalDt = Date.now() - dragStartTimeRef.current;
      const avgVelocity = totalDt > 0 ? currentDragYRef.current / totalDt : 1; // px/ms
      const duration = Math.max(200, Math.min(400, SNAP_THRESHOLD / avgVelocity));
      setExitDuration(duration);

      // Closing triggers the always-mounted CSS exit transition. The inline
      // transitionDuration style (picked up via `sheetStyle` below) overrides
      // the CSS class value with the velocity-based duration.
      onClose();

      // Schedule a second haptic pulse at the animation midpoint to simulate
      // the sheet clicking out of its rails — a short buzz when the threshold
      // is crossed, then a stronger pulse mid-flight.
      const midpoint = Math.floor(duration / 2);
      dismissHapticTimerRef.current = setTimeout(() => {
        haptic.midpoint();
        dismissHapticTimerRef.current = null;
      }, midpoint);
    } else {
      // Reset drag state — when style becomes undefined the CSS transition
      // animates the sheet back to its resting position.
      setDragY(0);
    }

    dragStartYRef.current = 0;
    currentDragYRef.current = 0;
  };

  // Backdrop opacity linked to drag distance: at drag=0 → 1.0, at drag=threshold → 0.6.
  // Always-mounted so the CSS transition can animate the fade-in/out smoothly.
  const backdropOpacity =
    !open
      ? 0
      : isDragging && dragY > 0
        ? Math.max(0.6, 1 - (dragY / SNAP_THRESHOLD) * 0.4)
        : 1;

  const backdropTransition =
    isDragging && dragY > 0
      ? "none"
      : "opacity 250ms var(--ease-out)";

  // When dragging, inline transform + transition:none overrides the CSS class.
  // On release, the inline style is removed and the CSS `.bottom-sheet--open`
  // or `.bottom-sheet` class transition handles the bounce-back or exit.
  //
  // When exitDuration is set (dismissing), inject an inline transition-duration
  // so the exit animation speed matches the user's drag velocity.
  const sheetStyle: React.CSSProperties | undefined =
    isDragging && dragY > 0
      ? {
          transform: `translateY(${dragY}px)`,
          transition: "none",
        }
      : exitDuration !== null
        ? { transitionDuration: `${exitDuration}ms, ${exitDuration}ms` }
        : undefined;

  return (
    <>
      {/* Backdrop — always-mounted with opacity + pointer-events for smooth
          transitions. When hidden, pointer-events: none so clicks pass through. */}
      <div
        className={`bottom-sheet-overlay${open ? " bottom-sheet-overlay--open" : ""}`}
        onClick={onClose}
        aria-hidden="true"
        style={{
          opacity: backdropOpacity,
          transition: backdropTransition,
          pointerEvents: open || isDragging ? "auto" : "none",
        }}
      />

      {/* Sheet — always-mounted for smooth enter/exit transitions.
          When hidden: position off-screen via CSS (translateY(100%) + opacity: 0).
          When visible: .bottom-sheet--open slides it in (translateY(0) + opacity: 1).
          Content inside is conditionally rendered so the DOM stays clean when closed. */}
      <div
        ref={sheetRef}
        className={`bottom-sheet${open ? " bottom-sheet--open" : ""}`}
        style={sheetStyle}
        role="dialog"
        aria-modal={open ? "true" : undefined}
        aria-hidden={!open || undefined}
        aria-label="Trade execution"
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onTouchCancel={handleTouchEnd}
      >
        {open && (
          <>
            {/* Drag handle */}
            <div className="bottom-sheet__handle">
              <div className="bottom-sheet__handle-bar" />
            </div>

            <div className="bottom-sheet__header">
              <span className="text-sm font-semibold text-[var(--text-strong)]">
                Trade execution
              </span>
              <button
                type="button"
                className="bottom-sheet__close"
                onClick={() => {
                  haptic.close();
                  onClose();
                }}
                aria-label="Close"
              >
                <XIcon />
              </button>
            </div>

            <div ref={bodyRef} className="bottom-sheet__body" onScroll={checkScrollBottom}>
              <TradeInstructionPanel
                call={call}
                guardianStatus={guardianStatus}
                trackedPosition={trackedPosition}
                executing={executing}
                executionMode={executionMode}
                provenOnly={provenOnly}
                onExecute={() => { onSubmitTrade(); onClose(); }}
                onClose={onCloseTrade}
                onSetExecutionMode={onSetExecutionMode}
                onSetProvenOnly={onSetProvenOnly}
              />
              {/* Fade gradient at bottom edge — visible only when content
                  overflows and isn't scrolled to the very end. A linear
                  gradient from transparent (top) to the body background
                  color (bottom) creates a subtle scrollability hint. */}
              <div
                aria-hidden="true"
                style={{
                  position: "sticky",
                  bottom: 0,
                  left: 0,
                  right: 0,
                  height: "2.5rem",
                  pointerEvents: "none",
                  opacity: atBottom ? 0 : 1,
                  transition: "opacity 300ms var(--ease-out)",
                  background: "linear-gradient(to bottom, transparent, var(--bg-panel-strong))",
                  marginTop: "-2.5rem",
                }}
              />
            </div>
          </>
        )}
      </div>
    </>
  );
}
