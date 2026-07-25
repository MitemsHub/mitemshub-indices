"use client";

import React, { useEffect, useState, useCallback } from "react";

type ConnectionStatusData = {
  mt5_configured: boolean;
  mt5_process_running: boolean;
  engine_root_configured: boolean;
  csv_ticks: Record<string, number>;
  last_warmup_at: string | null;
  engine_bridge_version: number;
  engine_version: string | null;
  mt5_last_error: string | null;
};

type Mt5TestResult = {
  success: boolean;
  error: string | null;
  server: string | null;
  terminal_path: string | null;
  duration_ms: number;
  account_name?: string;
  account_balance?: number;
};

type StatusFetcher = () => Promise<ConnectionStatusData>;
type TestFetcher = () => Promise<Mt5TestResult>;
type RetryFetcher = () => Promise<Mt5TestResult>;

export type ConnectionStatusProps = {
  /** Seed data — when provided the component skips the initial fetch and renders this data immediately. */
  initialData?: ConnectionStatusData | null;
  /** Custom status fetcher — defaults to GET /api/system/connection-status. */
  statusFetcher?: StatusFetcher;
  /** Custom test-MT5 fetcher — defaults to POST /api/system/test-mt5. */
  testFetcher?: TestFetcher;
  /** Custom retry-MT5 fetcher — defaults to POST /api/system/retry-mt5. */
  retryFetcher?: RetryFetcher;
  /** Poll interval in ms — defaults to 15000. */
  pollIntervalMs?: number;
};

function StatusDot({ active, color }: { active: boolean; color: string }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${active ? "animate-pulse" : ""}`}
      style={{
        background: active ? color : "var(--text-muted)",
        opacity: active ? 1 : 0.4,
      }}
      aria-hidden="true"
    />
  );
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "Never";
  const d = new Date(iso);
  const now = Date.now();
  const diff = now - d.getTime();
  if (diff < 0) return "Just now";
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
}

export function ConnectionStatus({
  initialData,
  statusFetcher,
  testFetcher,
  retryFetcher,
  pollIntervalMs = 15_000,
}: ConnectionStatusProps = {}) {
  const [data, setData] = useState<ConnectionStatusData | null>(
    initialData !== undefined ? initialData : null,
  );
  const [fetchError, setFetchError] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<Mt5TestResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);

  // Auto-dismiss test result toast after 5 seconds
  useEffect(() => {
    if (!testResult) return;
    const timer = setTimeout(() => setTestResult(null), 5000);
    return () => clearTimeout(timer);
  }, [testResult]);

  // Default fetcher — real HTTP call
  const defaultStatusFetcher: StatusFetcher = useCallback(async () => {
    const res = await fetch("/api/system/connection-status");
    if (!res.ok) throw new Error("Non-ok response");
    return res.json() as Promise<ConnectionStatusData>;
  }, []);

  const defaultTestFetcher: TestFetcher = useCallback(async () => {
    const res = await fetch("/api/system/test-mt5", { method: "POST" });
    return res.json() as Promise<Mt5TestResult>;
  }, []);

  const defaultRetryFetcher: RetryFetcher = useCallback(async () => {
    const res = await fetch("/api/system/retry-mt5", { method: "POST" });
    return res.json() as Promise<Mt5TestResult>;
  }, []);

  const effectiveStatusFetcher = statusFetcher ?? defaultStatusFetcher;
  const effectiveTestFetcher = testFetcher ?? defaultTestFetcher;
  const effectiveRetryFetcher = retryFetcher ?? defaultRetryFetcher;

  const fetchStatus = useCallback(async () => {
    try {
      const result = await effectiveStatusFetcher();
      setData(result);
      setFetchError(false);
    } catch {
      setFetchError(true);
    }
  }, [effectiveStatusFetcher]);

  useEffect(() => {
    // Skip initial fetch when initialData was provided
    if (initialData !== undefined) return;
    void fetchStatus();
    const interval = setInterval(fetchStatus, pollIntervalMs);
    return () => clearInterval(interval);
  }, [fetchStatus, pollIntervalMs, initialData]);

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    setTestError(null);
    try {
      const result = await effectiveTestFetcher();
      setTestResult(result);
    } catch {
      setTestError("Network error");
    } finally {
      setTesting(false);
      // Re-fetch status after test completes
      void fetchStatus();
    }
  };

  if (fetchError) {
    return (
      <div className="surface rounded-xl px-3 py-2 flex items-center gap-2 text-[11px] text-[var(--text-muted)] mb-3">
        <StatusDot active={false} color="var(--accent-danger)" />
        <span>Status unavailable</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="surface rounded-xl px-3 py-2 flex items-center gap-2 text-[11px] text-[var(--text-muted)] mb-3">
        <div className="w-2 h-2 rounded-full bg-[var(--line-subtle)] animate-pulse" />
        <span>Loading…</span>
      </div>
    );
  }

  const mt5Ok = data.mt5_configured && data.mt5_process_running;
  const mt5ConfiguredOnly = data.mt5_configured && !data.mt5_process_running;
  const mt5Error = data.mt5_last_error;
  const totalTicks = (data.csv_ticks["R_75"] ?? 0) + (data.csv_ticks["R_100"] ?? 0);

  // Build a detailed MT5 status message for the tooltip
  const mt5Tooltip = mt5Ok
    ? "Blueberry Markets MT5 terminal is running"
    : mt5ConfiguredOnly
      ? mt5Error
        ? `MT5 credentials configured but terminal disconnected: ${mt5Error}`
        : "MT5 credentials configured but terminal64.exe not detected"
      : "MT5 not configured (no server/login/password in .env.local)";

  return (
    <div className="surface rounded-xl px-3 py-2 flex items-center gap-3 text-[11px] text-[var(--text-body)] flex-wrap mb-3">
      {/* MT5 status */}
      <span className="flex items-center gap-1.5" title={mt5Tooltip}>
        <StatusDot active={mt5Ok} color="var(--accent-positive)" />
        <span className="font-medium">MT5:</span>
        <span className={mt5Ok ? "text-[var(--accent-positive)]" : mt5ConfiguredOnly ? "text-[var(--accent-warn)]" : "text-[var(--text-muted)]"}>
          {mt5Ok ? "Connected" : mt5ConfiguredOnly ? (mt5Error ? "Error" : "Not running") : "Off"}
        </span>
      </span>

      {/* Test MT5 button — only when credentials are configured */}
      {data.mt5_configured && (
        <button
          type="button"
          className="flex items-center gap-1 rounded-md border border-[var(--line-subtle)] bg-transparent px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-muted)] hover:bg-[var(--bg-surface-hover)] hover:text-[var(--text-body)] active:scale-95 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          onClick={runTest}
          disabled={testing}
          title={testing ? "Testing MT5 connection…" : "Run MT5 health check: initialize + login"}
          aria-label="Test MT5 connection"
        >
          {testing ? (
            <>
              <span className="inline-block w-2 h-2 rounded-full bg-[var(--accent-ink)] animate-pulse" />
              Testing…
            </>
          ) : (
            "Test"
          )}
        </button>
      )}

      {/* MT5 error detail — shown only when configured but disconnected with a known error */}
      {mt5ConfiguredOnly && mt5Error && (
        <span
          className="flex items-center gap-1.5 max-w-[240px] truncate"
          title={mt5Error}
        >
          <span className="text-[10px] text-[var(--accent-danger)] font-medium">
            {mt5Error.length > 55 ? mt5Error.slice(0, 55) + "…" : mt5Error}
          </span>
          {/* Retry button — re-runs the Python initialize/login flow */}
          <button
            type="button"
            className="flex items-center gap-1 rounded-md border border-[var(--line-subtle)] bg-transparent px-1.5 py-0.5 text-[9px] font-medium text-[var(--accent-ink)] hover:bg-[var(--accent-ink-soft)] active:scale-95 transition-all disabled:opacity-40 disabled:cursor-not-allowed ml-1"
            onClick={async () => {
              setTesting(true);
              try {
                const result = await effectiveRetryFetcher();
                setTestResult(result);
                if (result.success) {
                  // Re-fetch status immediately so the error badge disappears
                  void fetchStatus();
                }
              } catch {
                // Silently ignore — next poll will re-check
              } finally {
                setTesting(false);
              }
            }}
            disabled={testing}
            title="Retry MT5 connection — runs initialize + login again"
            aria-label="Retry MT5 connection"
          >
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <polyline points="23 4 23 10 17 10" />
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
            </svg>
            Retry
          </button>
        </span>
      )}

      {/* Live test result toast — visible briefly after test completes */}
      {testResult && !testing && (
        <span
          className={`flex items-center gap-1.5 text-[10px] max-w-[320px] ${
            testResult.success ? "text-[var(--accent-positive)]" : "text-[var(--accent-danger)]"
          }`}
          title={testResult.error ?? "Connected successfully"}
        >
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${
              testResult.success ? "bg-[var(--accent-positive)]" : "bg-[var(--accent-danger)]"
            }`}
          />
          {testResult.success
            ? `OK ${testResult.duration_ms}ms`
            : (testResult.error ?? "Failed").length > 60
              ? (testResult.error ?? "Failed").slice(0, 60) + "…"
              : testResult.error ?? "Failed"}
        </span>
      )}

      {testError && !testing && (
        <span className="text-[10px] text-[var(--accent-danger)]">{testError}</span>
      )}

      <span className="w-px h-3 bg-[var(--line-subtle)]" />

      {/* CSV ticks */}
      <span className="flex items-center gap-1.5" title="Total tick lines in CSV data files">
        <StatusDot active={totalTicks > 0} color="var(--accent-ink)" />
        <span className="font-medium">CSV:</span>
        <span>{totalTicks.toLocaleString()} ticks</span>
        {data.csv_ticks["R_75"] != null && data.csv_ticks["R_100"] != null && (
          <span className="text-[10px] text-[var(--text-muted)]">
            (V75: {data.csv_ticks["R_75"].toLocaleString()} &middot; V100: {data.csv_ticks["R_100"].toLocaleString()})
          </span>
        )}
      </span>

      <span className="w-px h-3 bg-[var(--line-subtle)]" />

      {/* Warmup timestamp */}
      <span className="flex items-center gap-1.5" title="Last time the background warmup cycle ran">
        <StatusDot active={data.last_warmup_at !== null} color="var(--accent-positive)" />
        <span className="font-medium">Warmup:</span>
        <span>{formatTimestamp(data.last_warmup_at)}</span>
      </span>

      {/* Engine version — shown only when available */}
      {data.engine_version && (
        <>
          <span className="w-px h-3 bg-[var(--line-subtle)]" />
          <span className="flex items-center gap-1.5" title="Python engine package version">
            <span className="font-medium">Engine:</span>
            <span className="text-[var(--text-muted)]">v{data.engine_version}</span>
          </span>
        </>
      )}
    </div>
  );
}
