"use client";

import React, { useEffect, useRef, type ReactNode } from "react";

type BottomSheetProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
};

export function BottomSheet({ open, onClose, title, children }: BottomSheetProps) {
  const sheetRef = useRef<HTMLDivElement>(null);
  const startY = useRef<number>(0);
  const currentY = useRef<number>(0);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  // Prevent body scroll when open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  // Touch drag to dismiss
  const onTouchStart = (e: React.TouchEvent) => {
    startY.current = e.touches[0].clientY;
  };

  const onTouchMove = (e: React.TouchEvent) => {
    currentY.current = e.touches[0].clientY;
    const diff = currentY.current - startY.current;
    if (diff > 0 && sheetRef.current) {
      sheetRef.current.style.transform = `translateY(${Math.min(diff, 200)}px)`;
    }
  };

  const onTouchEnd = () => {
    const diff = currentY.current - startY.current;
    if (diff > 80 && sheetRef.current) {
      sheetRef.current.style.transform = "";
      onClose();
    } else if (sheetRef.current) {
      sheetRef.current.style.transform = "";
    }
    startY.current = 0;
    currentY.current = 0;
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className={`bottom-sheet-backdrop ${open ? "bottom-sheet-backdrop--open" : ""}`}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Sheet */}
      <div
        ref={sheetRef}
        className={`bottom-sheet ${open ? "bottom-sheet--open" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
      >
        {/* Drag handle */}
        <div className="bottom-sheet__handle" aria-hidden="true">
          <span className="bottom-sheet__handle-bar" />
        </div>

        {/* Header */}
        <div className="bottom-sheet__header">
          <h3 className="display-serif text-lg font-semibold text-[var(--text-strong)]">
            {title}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="bottom-sheet__close"
            aria-label="Close"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="bottom-sheet__body">
          {children}
        </div>
      </div>
    </>
  );
}
