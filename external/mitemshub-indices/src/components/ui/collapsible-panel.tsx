"use client";

import React, { useState, useCallback, useRef, useEffect } from "react";

type CollapsiblePanelProps = {
  /** Panel title shown in the header */
  title: string;
  /** Whether the panel is enabled/visible at all */
  enabled?: boolean;
  /** Force expanded state (for desktop) */
  forceExpanded?: boolean;
  /** Content to render inside the panel */
  children: React.ReactNode;
  /** Optional className for the wrapper */
  className?: string;
};

/**
 * CollapsiblePanel — a panel that collapses on mobile viewports (<md)
 * and stays expanded on desktop (≥md). Uses CSS transitions for smooth
 * expand/collapse animation.
 *
 * Tier 3-4 intelligence panels should use this wrapper on mobile to
 * reduce scroll depth and cognitive load.
 */
export function CollapsiblePanel({
  title,
  enabled = true,
  forceExpanded = false,
  children,
  className = "",
}: CollapsiblePanelProps) {
  const [expanded, setExpanded] = useState(forceExpanded);
  const contentRef = useRef<HTMLDivElement>(null);
  const [contentHeight, setContentHeight] = useState<number | "auto">(forceExpanded ? "auto" : 0);
  const panelId = useRef(`collapsible-${Math.random().toString(36).slice(2, 9)}`).current;

  // Measure content height when expanded
  useEffect(() => {
    if (expanded && contentRef.current) {
      const height = contentRef.current.scrollHeight;
      setContentHeight(height);
      const timer = setTimeout(() => setContentHeight("auto"), 350);
      return () => clearTimeout(timer);
    }
  }, [expanded]);

  const toggle = useCallback(() => {
    if (forceExpanded || !enabled) return;
    setExpanded((prev) => {
      if (prev && contentRef.current) {
        // Collapsing — capture current height before state change
        const h = contentRef.current.scrollHeight;
        setContentHeight(h);
        requestAnimationFrame(() => setContentHeight(0));
      } else if (!prev && contentRef.current) {
        // Expanding — measure target height
        setContentHeight(contentRef.current.scrollHeight);
        setTimeout(() => setContentHeight("auto"), 350);
      }
      return !prev;
    });
  }, [forceExpanded, enabled]);

  if (!enabled) return null;

  return (
    <div className={`collapsible-panel ${className}`}>
      <button
        type="button"
        onClick={toggle}
        className="collapsible-panel__header"
        aria-expanded={expanded}
        aria-controls={panelId}
      >
        <span className="collapsible-panel__title">{title}</span>
        <span
          className={`collapsible-panel__chevron ${expanded ? "collapsible-panel__chevron--open" : ""}`}
          aria-hidden="true"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </span>
      </button>

      <div
        id={panelId}
        className="collapsible-panel__content"
        role="region"
        style={{
          height: expanded ? (typeof contentHeight === "number" ? `${contentHeight}px` : "auto") : "0px",
          opacity: expanded ? 1 : 0,
          overflow: expanded ? "visible" : "hidden",
        }}
      >
        <div ref={contentRef} className="collapsible-panel__inner">
          {children}
        </div>
      </div>

      <style jsx>{`
        .collapsible-panel {
          border: 1px solid var(--line-subtle);
          border-radius: 1.25rem;
          background: var(--bg-panel);
          overflow: hidden;
          transition: border-color 300ms ease;
        }

        .collapsible-panel__header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          width: 100%;
          padding: 0.75rem 1rem;
          background: transparent;
          border: none;
          cursor: pointer;
          text-align: left;
          transition: background 200ms ease;
        }

        .collapsible-panel__header:hover {
          background: var(--bg-surface-hover);
        }

        .collapsible-panel__title {
          font-family: "Inter", "Segoe UI", system-ui, sans-serif;
          font-size: 0.75rem;
          font-weight: 600;
          letter-spacing: 0.06em;
          text-transform: uppercase;
          color: var(--text-muted);
        }

        .collapsible-panel__chevron {
          display: flex;
          align-items: center;
          justify-content: center;
          width: 1.25rem;
          height: 1.25rem;
          color: var(--text-muted);
          transition: transform 300ms var(--ease-out);
          transform: rotate(-90deg);
        }

        .collapsible-panel__chevron--open {
          transform: rotate(0deg);
        }

        .collapsible-panel__content {
          transition: height 350ms var(--ease-out), opacity 300ms ease;
        }

        .collapsible-panel__inner {
          padding: 0 1rem 1rem;
        }

        /* Desktop: always expanded, hide header */
        @media (min-width: 768px) {
          .collapsible-panel__header {
            display: none;
          }
          .collapsible-panel__content {
            height: auto !important;
            opacity: 1 !important;
            overflow: visible !important;
          }
          .collapsible-panel__inner {
            padding: 1rem;
          }
        }
      `}</style>
    </div>
  );
}
