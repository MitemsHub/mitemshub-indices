"use client";

import React, { useEffect, useState, useCallback } from "react";

type SubprocessHistoryEntry = {
  label: string;
  durationMs: number;
  timestamp: number;
  success: boolean;
};

type DiagnosticsData = {
  lastGuardianReason: string | null;
  lastStderr: string | null;
  lastRetryCount: number;
  lastError: string | null;
  lastUpdatedAt: string | null;
  staleDataSince: number | null;
  lastSubprocessDurationMs: number | null;
  lastSubprocessLabel: string | null;
  subprocessHistory: SubprocessHistoryEntry[];
};

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

/** Compute human-readable staleness from an epoch-seconds timestamp.
 *  Returns a string like "12.3h", "47h", or "30m" depending on the duration.
 *  Returns null if the epoch is null/invalid. */
function formatStaleness(epochSeconds: number | null): string | null {
  if (typeof epochSeconds !== "number" || !Number.isFinite(epochSeconds)) return null;
  const deltaSeconds = Date.now() / 1000 - epochSeconds;
  if (deltaSeconds < 0) return "Just now";
  if (deltaSeconds < 60) return `${Math.floor(deltaSeconds)}s`;
  if (deltaSeconds < 3600) return `${Math.floor(deltaSeconds / 60)}m`;
  const hours = deltaSeconds / 3600;
  if (hours < 100) return `${hours.toFixed(1)}h`;
  return `${Math.floor(hours)}h`;
}

function DiagnosticsRow({
  label,
  value,
  monospace = false,
  collapsed = false,
}: {
  label: string;
  value: string | null;
  monospace?: boolean;
  collapsed?: boolean;
}) {
  if (!value) return null;

  const display = collapsed && value.length > 200 ? value.slice(0, 200) + "..." : value;

  return (
    <div className="space-y-1">
      <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
        {label}
      </p>
      <pre
        className={`rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2.5 py-2 text-[11px] leading-relaxed whitespace-pre-wrap break-all ${
          monospace ? "font-mono" : "font-sans"
        } ${
          value.length > 200
            ? "text-[var(--accent-warn)]"
            : "text-[var(--text-body)]"
        }`}
      >
        {display}
      </pre>
    </div>
  );
}

export function PipelineDiagnosticsPanel() {
  const [data, setData] = useState<DiagnosticsData | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [fetchError, setFetchError] = useState(false);
  const [collecting, setCollecting] = useState(false);
  const [collectResult, setCollectResult] = useState<string | null>(null);

  // useCallback keeps a stable reference for the useEffect dependency.
  // Without it, the effect would re-run on every render.
  const fetchDiagnostics = useCallback(async () => {
    try {
      const res = await fetch("/api/system/pipeline-diagnostics");
      if (!res.ok) throw new Error("Non-ok response");
      const result = (await res.json()) as DiagnosticsData;
      setData(result);
      setFetchError(false);
    } catch {
      setFetchError(true);
    }
  }, []);

  useEffect(() => {
    void fetchDiagnostics();
    const interval = setInterval(fetchDiagnostics, 10_000);
    return () => clearInterval(interval);
  }, [fetchDiagnostics]);

  const handleCollectTicks = async () => {
    setCollecting(true);
    setCollectResult(null);
    try {
      const res = await fetch("/api/system/collect-ticks", { method: "POST" });
      if (!res.ok) throw new Error("Non-ok response");
      const result = (await res.json()) as {
        collected: number;
        errors: string[];
        duration_ms: number;
      };
      if (result.errors && result.errors.length > 0) {
        setCollectResult(`Collected with errors: ${result.errors.join("; ")}`);
      } else if (result.collected === -1) {
        setCollectResult("Warmup already in progress — tick collection will follow");
      } else {
        setCollectResult(
          `Collected ${result.collected} tick sample(s) in ${(result.duration_ms / 1000).toFixed(1)}s`,
        );
      }
      // Refresh diagnostics after collection
      void fetchDiagnostics();
    } catch {
      setCollectResult("Failed to trigger tick collection");
    } finally {
      setCollecting(false);
    }
  };

  const hasData = data && (data.lastGuardianReason || data.lastStderr || data.lastError || data.lastRetryCount > 0);
  const hasIssues = data?.lastStderr || data?.lastError || (data?.lastRetryCount ?? 0) > 0;

  return (
    <div className="surface rounded-xl mt-2">
      {/* Toggle header */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-[11px] text-[var(--text-muted)] hover:text-[var(--text-body)] transition-colors"
        aria-expanded={expanded}
        aria-label="Toggle pipeline diagnostics"
      >
        <span className="flex items-center gap-2">
          {/* Status indicator */}
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              fetchError
                ? "bg-[var(--accent-danger)]"
                : hasIssues
                  ? "bg-[var(--accent-warn)]"
                  : hasData
                    ? "bg-[var(--accent-positive)]"
                    : "bg-[var(--text-muted)]"
            }`}
            aria-hidden="true"
          />
          <span className="font-medium tracking-wide uppercase">
            Pipeline Diagnostics
          </span>
          {!expanded && data && (
            <span className="text-[10px] text-[var(--text-muted)]">
              {hasIssues ? (
                <span className="text-[var(--accent-warn)]">
                  {data.lastError ? "Error" : data.lastStderr ? "Stderr" : `${data.lastRetryCount} retr${data.lastRetryCount === 1 ? "y" : "ies"}`}
                </span>
              ) : data.lastGuardianReason ? (
                "OK"
              ) : "No data"}
              &middot; {formatTimestamp(data.lastUpdatedAt)}
            </span>
          )}
        </span>
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
          aria-hidden="true"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="px-3 pb-3 space-y-3">
          <div className="h-px bg-[var(--line-subtle)]" />

          {fetchError ? (
            <p className="text-[11px] text-[var(--accent-danger)]">
              Pipeline diagnostics unavailable. The diagnostics endpoint may not be implemented yet.
            </p>
          ) : !data ? (
            <div className="flex items-center gap-2 text-[11px] text-[var(--text-muted)]">
              <div className="w-2 h-2 rounded-full bg-[var(--line-subtle)] animate-pulse" />
              Loading diagnostics...
            </div>
          ) : !hasData ? (
            <p className="text-[11px] text-[var(--text-muted)] italic">
              No diagnostic data recorded yet. Run a live call to populate.
            </p>
          ) : (
            <>
              {/* Summary status */}
              <div className="flex flex-wrap items-center gap-3 text-[11px]">
                <span className="flex items-center gap-1.5">
                  <span className="text-[var(--text-label)]">Retries:</span>
                  <span className={`font-mono font-semibold ${data.lastRetryCount > 0 ? "text-[var(--accent-warn)]" : "text-[var(--text-body)]"}`}>
                    {data.lastRetryCount}
                  </span>
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="text-[var(--text-label)]">Updated:</span>
                  <span className="font-mono text-[var(--text-body)]">
                    {formatTimestamp(data.lastUpdatedAt)}
                  </span>
                </span>
                {/* Data staleness — computed from staleDataSince epoch */}
                {(() => {
                  const staleness = formatStaleness(data.staleDataSince);
                  return staleness ? (
                    <span className="flex items-center gap-1.5">
                      <span className="text-[var(--text-label)]">Staleness:</span>
                      <span className="font-mono font-semibold text-[var(--accent-warn)]">
                        {staleness}
                      </span>
                    </span>
                  ) : null;
                })()}
                {data.lastSubprocessDurationMs != null && (
                  <span className="flex items-center gap-1.5">
                    <span className="text-[var(--text-label)]">Response:</span>
                    <span className={`font-mono font-semibold ${
                      data.lastSubprocessDurationMs > 15000 ? "text-[var(--accent-danger)]" :
                      data.lastSubprocessDurationMs > 8000 ? "text-[var(--accent-warn)]" :
                      "text-[var(--accent-positive)]"
                    }`}>
                      {(data.lastSubprocessDurationMs / 1000).toFixed(1)}s
                    </span>
                    {data.lastSubprocessLabel && (
                      <span className="text-[10px] text-[var(--text-muted)] font-mono">
                        ({data.lastSubprocessLabel})
                      </span>
                    )}
                  </span>
                )}
                {(data.lastStderr || data.lastError) && (
                  <span className="inline-flex items-center gap-1 rounded-full border border-[var(--accent-danger)] bg-[var(--accent-danger-soft)] px-2 py-0.5 text-[10px] font-semibold text-[var(--accent-danger)]">
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--accent-danger)]" />
                    Issue detected
                  </span>
                )}
              </div>

              {/* Subprocess Timing History */}
              {data.subprocessHistory && data.subprocessHistory.length > 0 && (
                <DiagnosticsRow
                  label="Recent Subprocess Calls"
                  value={data.subprocessHistory
                    .slice(-5)
                    .reverse()
                    .map((e) => {
                      const time = new Date(e.timestamp).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
                      const status = e.success ? "✓" : "✗";
                      const duration = `${(e.durationMs / 1000).toFixed(1)}s`;
                      return `${status} ${time} ${duration} ${e.label}`;
                    })
                    .join("\n")}
                  monospace
                />
              )}

              {/* Guardian Reason */}
              {data.lastGuardianReason && (
                <DiagnosticsRow
                  label="Guardian Reason"
                  value={data.lastGuardianReason}
                  collapsed={data.lastGuardianReason.length > 200}
                />
              )}

              {/* Error */}
              {data.lastError && (
                <DiagnosticsRow
                  label="Last Error"
                  value={data.lastError}
                  monospace
                  collapsed={data.lastError.length > 200}
                />
              )}

              {/* Stderr */}
              {data.lastStderr && (
                <DiagnosticsRow
                  label="Python Stderr"
                  value={data.lastStderr}
                  monospace
                  collapsed={data.lastStderr.length > 200}
                />
              )}

              {/* Collect Fresh Ticks button */}
              <div className="pt-1">
                <button
                  type="button"
                  onClick={handleCollectTicks}
                  disabled={collecting}
                  className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[10px] font-medium transition-all ${
                    collecting
                      ? "border-[var(--line-subtle)] text-[var(--text-muted)] cursor-not-allowed"
                      : "border-[var(--accent-ink)] text-[var(--accent-ink)] hover:bg-[var(--accent-ink)] hover:text-white"
                  }`}
                >
                  {collecting ? (
                    <>
                      <span className="inline-block w-1.5 h-1.5 rounded-full bg-[var(--accent-warn)] animate-pulse" />
                      Collecting…
                    </>
                  ) : (
                    <>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M12 20h9" />
                        <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                      </svg>
                      Collect Fresh Ticks
                    </>
                  )}
                </button>
                {collectResult && (
                  <p className={`mt-1.5 text-[10px] ${
                    collectResult.startsWith("Failed") || collectResult.startsWith("Collected with errors")
                      ? "text-[var(--accent-warn)]"
                      : "text-[var(--text-muted)]"
                  }`}>
                    {collectResult}
                  </p>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
