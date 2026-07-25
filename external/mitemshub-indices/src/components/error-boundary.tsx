"use client";

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="min-h-screen flex items-center justify-center bg-[var(--bg-canvas)] px-4">
            <div className="surface rounded-2xl p-8 max-w-lg text-center shadow-[var(--shadow-elevated)]">
              <div className="pulse-dot pulse-dot--danger mx-auto mb-4" aria-hidden="true" />
              <p className="display-serif text-xl font-semibold text-[var(--text-strong)]">
                Something went wrong
              </p>
              <p className="mt-2 text-sm leading-6 text-[var(--text-body)]">
                {this.state.error?.message || "An unexpected error occurred."}
              </p>
              <button
                className="primary-action mt-5 rounded-xl bg-[var(--accent-ink)] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[var(--accent-ink-hover)]"
                onClick={() => this.setState({ hasError: false, error: null })}
              >
                Try again
              </button>
            </div>
          </div>
        )
      );
    }
    return this.props.children;
  }
}
