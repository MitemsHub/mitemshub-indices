"use client";

import React, { Component, type ReactNode } from "react";

type ErrorBoundaryProps = {
  children: ReactNode;
  /** Optional — custom fallback rendered on error. Defaults to a dimmed status-bar pill. */
  fallback?: ReactNode;
  /** A label shown in the fallback to identify which component crashed. */
  label?: string;
};

type ErrorBoundaryState = {
  hasError: boolean;
  error: Error | null;
};

/**
 * Catches render errors in downstream children and renders a controlled
 * fallback instead of unmounting the entire React tree.
 *
 * In production this prevents a single broken API response or unexpected
 * null from taking down the entire operator shell.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error(`[ErrorBoundary](op/error-boundary)${this.props.label ? ` ${this.props.label}` : ""}:`, error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback !== undefined) {
        return this.props.fallback;
      }

      // Default fallback — a compact, dimmed bar that doesn't break layout.
      return (
        <div className="surface rounded-xl px-3 py-2 text-[11px] text-[var(--text-muted)] mb-3">
          <span className="flex items-center gap-2">
            <span
              className="inline-block w-2 h-2 rounded-full bg-[var(--accent-danger)]"
              aria-hidden="true"
            />
            {this.props.label ? `${this.props.label} unavailable` : "Widget unavailable"}
          </span>
        </div>
      );
    }

    return this.props.children;
  }
}
