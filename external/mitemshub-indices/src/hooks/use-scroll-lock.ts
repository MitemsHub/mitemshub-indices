"use client";

import { useEffect, useRef } from "react";

/**
 * Module-level counter tracking how many components have locked body scroll.
 * Only sets `overflow = "hidden"` when the counter moves from 0 → 1,
 * and only clears it when the counter returns to 0.
 *
 * This allows nested modals / sheets / overlays to all acquire the lock
 * without stepping on each other — closing one never unlocks the scroll
 * while another is still visible.
 */
let scrollLockCount = 0;

function lockScroll(): void {
  scrollLockCount += 1;
  if (scrollLockCount === 1) {
    document.body.style.overflow = "hidden";
  }
}

function unlockScroll(): void {
  scrollLockCount = Math.max(0, scrollLockCount - 1);
  if (scrollLockCount === 0) {
    document.body.style.overflow = "";
  }
}

/**
 * Prevents body scroll when `locked` is true. Uses a module-level
 * ref counter so that multiple overlays can each acquire the lock
 * independently — closing one never unlocks the scroll while another
 * is still visible.
 */
export function useScrollLock(locked: boolean): void {
  const hasLock = useRef(false);

  useEffect(() => {
    if (locked) {
      lockScroll();
      hasLock.current = true;
    }
    return () => {
      if (hasLock.current) {
        unlockScroll();
        hasLock.current = false;
      }
    };
  }, [locked]);
}
