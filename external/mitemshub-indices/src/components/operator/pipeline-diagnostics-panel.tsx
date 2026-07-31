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

type SseStateTransition = {
  state: "connected" | "disconnected" | "error";
  timestamp: number;
  message?: string;
};

type SseStatusData = {
  activeConnections: number;
  maxConnections: number;
  stateHistory: SseStateTransition[];
  cacheStats: { hits: number; misses: number; hitRatio: number };
  uptime: number;
};

type ReplayBufferSymbolStats = {
  buffer_size: number;
  capacity: number;
  fill_pct: number;
  total_seen: number;
  mini_batch_size: number;
  replay_ratio: number;
  label_0_count: number;
  label_1_count: number;
  label_balance: number;
  model_updates: number;
  model_version: string;
} | null | { error: string };

type ReplayBufferStats = {
  r_75: ReplayBufferSymbolStats;
  r_100: ReplayBufferSymbolStats;
};

type CalibrationSymbolStats = {
  total_samples: number;
  positive_count: number;
  negative_count: number;
  avg_prediction: number;
  accuracy: number;
  model_updates: number;
  model_version: string;
  ready: boolean;
  progress_pct: number;
  loaded_from_disk?: boolean;
  save_count?: number;
  brier_score?: number | null;
  last_save_epoch?: number;
  last_save_age_seconds?: number;
  file_size_bytes?: number;
} | null | { error: string };

type CalibrationStats = Record<string, CalibrationSymbolStats>;

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
  const [sseStatus, setSseStatus] = useState<SseStatusData | null>(null);
  const [replayStats, setReplayStats] = useState<ReplayBufferStats | null>(null);
  const [calibrationStats, setCalibrationStats] = useState<CalibrationStats | null>(null);

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
    const fetchSseStatus = async () => {
      try {
        const res = await fetch("/api/system/sse-status");
        if (res.ok) {
          setSseStatus(await res.json());
        }
      } catch {
        // SSE status unavailable — not critical
      }
    };
    const fetchReplayStats = async () => {
      try {
        const res = await fetch("/api/system/replay-buffer-stats");
        if (res.ok) {
          setReplayStats(await res.json());
        }
      } catch {
        // Replay stats unavailable — not critical
      }
    };
    const fetchCalibrationStats = async () => {
      try {
        const res = await fetch("/api/system/calibration-stats");
        if (res.ok) {
          setCalibrationStats(await res.json());
        }
      } catch {
        // Calibration stats unavailable — not critical
      }
    };
    void fetchSseStatus();
    void fetchReplayStats();
    void fetchCalibrationStats();
    const interval = setInterval(() => {
      void fetchDiagnostics();
      void fetchSseStatus();
      void fetchReplayStats();
      void fetchCalibrationStats();
    }, 10_000);
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
  // Only flag as "issues" when there are actual errors or retries.
  // lastStderr contains informational Python output (e.g. outlier tick
  // warnings) — not real errors, so it should not trigger the badge.
  const hasIssues = data?.lastError || (data?.lastRetryCount ?? 0) > 0;

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
                    Issues detected
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

              {/* SSE Connection Status */}
              {sseStatus && (
                <div className="space-y-2">
                  <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
                    SSE Streaming
                  </p>
                  <div className="flex flex-wrap items-center gap-3 text-[11px]">
                    <span className="flex items-center gap-1.5">
                      <span className="text-[var(--text-label)]">Connections:</span>
                      <span className={`font-mono font-semibold ${
                        sseStatus.activeConnections >= sseStatus.maxConnections
                          ? "text-[var(--accent-danger)]"
                          : sseStatus.activeConnections > 0
                            ? "text-[var(--accent-positive)]"
                            : "text-[var(--text-body)]"
                      }`}>
                        {sseStatus.activeConnections}/{sseStatus.maxConnections}
                      </span>
                    </span>
                    {sseStatus.cacheStats && (
                      <span className="flex items-center gap-1.5">
                        <span className="text-[var(--text-label)]">Cache:</span>
                        <span className="font-mono text-[var(--text-body)]">
                          {Math.round(sseStatus.cacheStats.hitRatio * 100)}% hit
                        </span>
                        <span className="text-[10px] text-[var(--text-muted)]">
                          ({sseStatus.cacheStats.hits}h/{sseStatus.cacheStats.misses}m)
                        </span>
                      </span>
                    )}
                    {sseStatus.uptime > 0 && (
                      <span className="flex items-center gap-1.5">
                        <span className="text-[var(--text-label)]">Uptime:</span>
                        <span className="font-mono text-[var(--text-body)]">
                          {sseStatus.uptime < 60_000
                            ? `${Math.floor(sseStatus.uptime / 1000)}s`
                            : sseStatus.uptime < 3_600_000
                              ? `${Math.floor(sseStatus.uptime / 60_000)}m`
                              : `${(sseStatus.uptime / 3_600_000).toFixed(1)}h`}
                        </span>
                      </span>
                    )}
                  </div>
                  {sseStatus.stateHistory.length > 0 && (
                    <div className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2.5 py-2">
                      <p className="text-[10px] text-[var(--text-label)] mb-1.5 font-medium uppercase tracking-[0.12em]">
                        Connection History
                      </p>
                      <div className="space-y-0.5">
                        {sseStatus.stateHistory
                          .slice(-8)
                          .reverse()
                          .map((entry, i) => {
                            const time = new Date(entry.timestamp).toLocaleTimeString("en-US", {
                              hour: "2-digit",
                              minute: "2-digit",
                              second: "2-digit",
                            });
                            const icon = entry.state === "connected" ? "●" : entry.state === "disconnected" ? "○" : "✗";
                            const color = entry.state === "connected"
                              ? "text-[var(--accent-positive)]"
                              : entry.state === "disconnected"
                                ? "text-[var(--text-muted)]"
                                : "text-[var(--accent-danger)]";
                            return (
                              <div key={i} className="flex items-center gap-2 text-[10px] font-mono">
                                <span className={color}>{icon}</span>
                                <span className="text-[var(--text-muted)]">{time}</span>
                                <span className="text-[var(--text-body)]">
                                  {entry.state === "connected" ? "Connected" : entry.state === "disconnected" ? "Disconnected" : entry.message || "Error"}
                                </span>
                              </div>
                            );
                          })}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Replay Buffer Stats */}
              {replayStats && (
                <div className="space-y-2">
                  <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
                    Replay Buffer
                  </p>
                  {(["r_75", "r_100"] as const).map((symbol) => {
                    const stats = replayStats[symbol];
                    const symbolLabel = symbol === "r_75" ? "V75" : "V100";
                    // Model not loaded yet
                    if (stats === null) {
                      return (
                        <div key={symbol} className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2.5 py-2">
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] font-mono font-semibold text-[var(--text-strong)] uppercase">{symbolLabel}</span>
                            <span className="text-[10px] text-[var(--text-muted)] italic">No model loaded</span>
                          </div>
                        </div>
                      );
                    }
                    if (!stats || "error" in stats) {
                      const errMsg = stats && "error" in stats ? (stats as { error: string }).error : "Unavailable";
                      return (
                        <div key={symbol} className="rounded-lg border border-[var(--accent-danger)] bg-[var(--accent-danger-soft)] px-2.5 py-2">
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] font-mono font-semibold text-[var(--text-strong)] uppercase">{symbolLabel}</span>
                            <span className="text-[10px] text-[var(--accent-danger)]">{errMsg}</span>
                          </div>
                        </div>
                      );
                    }
                    const s = stats as { buffer_size: number; capacity: number; fill_pct: number; total_seen: number; mini_batch_size: number; replay_ratio: number; label_0_count: number; label_1_count: number; label_balance: number; model_updates: number; model_version: string };
                    const fillColor = s.fill_pct > 80 ? "bg-[var(--accent-positive)]" : s.fill_pct > 50 ? "bg-[var(--accent-ink)]" : "bg-[var(--text-muted)]";
                    return (
                      <div key={symbol} className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2.5 py-2">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-[10px] font-mono font-semibold text-[var(--text-strong)] uppercase">
                            {symbol === "r_75" ? "V75" : "V100"}
                          </span>
                          <span className="text-[10px] text-[var(--text-muted)] font-mono">
                            v{s.model_version} · {s.model_updates} updates
                          </span>
                        </div>
                        {/* Fill bar */}
                        <div className="h-1.5 rounded-full bg-[var(--line-subtle)] overflow-hidden mb-1.5">
                          <div className={`h-full rounded-full ${fillColor} transition-all duration-500`} style={{ width: `${Math.min(s.fill_pct, 100)}%` }} />
                        </div>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]">
                          <span className="flex items-center gap-1">
                            <span className="text-[var(--text-label)]">Fill:</span>
                            <span className="font-mono font-semibold text-[var(--text-body)]">{s.buffer_size.toLocaleString()}/{s.capacity.toLocaleString()} ({s.fill_pct}%)</span>
                          </span>
                          <span className="flex items-center gap-1">
                            <span className="text-[var(--text-label)]">Seen:</span>
                            <span className="font-mono text-[var(--text-body)]">{s.total_seen.toLocaleString()}</span>
                          </span>
                          <span className="flex items-center gap-1">
                            <span className="text-[var(--text-label)]">Batch:</span>
                            <span className="font-mono text-[var(--text-body)]">{s.mini_batch_size}</span>
                          </span>
                          <span className="flex items-center gap-1">
                            <span className="text-[var(--text-label)]">Ratio:</span>
                            <span className="font-mono text-[var(--text-body)]">{s.replay_ratio}</span>
                          </span>
                        </div>
                        {/* Label distribution */}
                        <div className="mt-1.5 flex items-center gap-2">
                          <span className="text-[10px] text-[var(--text-label)]">Labels:</span>
                          <div className="flex-1 h-1 rounded-full bg-[var(--line-subtle)] overflow-hidden flex">
                            <div className="h-full bg-[var(--accent-positive)]" style={{ width: `${(1 - s.label_balance) * 100}%` }} />
                            <div className="h-full bg-[var(--accent-danger)]" style={{ width: `${s.label_balance * 100}%` }} />
                          </div>
                          <span className="text-[10px] font-mono text-[var(--text-muted)]">
                            {s.label_1_count}↑ / {s.label_0_count}↓
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Learning Progress — Calibration Buffer */}
              {calibrationStats && Object.keys(calibrationStats).length > 0 && (
                <div className="space-y-2">
                  <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
                    Learning Progress
                  </p>
                  {Object.entries(calibrationStats).map(([key, stats]) => {
                    const label = key.replace(/_/g, " ").toUpperCase();
                    if (stats === null) {
                      return (
                        <div key={key} className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2.5 py-2">
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] font-mono font-semibold text-[var(--text-strong)] uppercase">{label}</span>
                            <span className="text-[10px] text-[var(--text-muted)] italic">No model loaded</span>
                          </div>
                        </div>
                      );
                    }
                    if ("error" in stats) {
                      return (
                        <div key={key} className="rounded-lg border border-[var(--accent-danger)] bg-[var(--accent-danger-soft)] px-2.5 py-2">
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] font-mono font-semibold text-[var(--text-strong)] uppercase">{label}</span>
                            <span className="text-[10px] text-[var(--accent-danger)]">{(stats as { error: string }).error}</span>
                          </div>
                        </div>
                      );
                    }
                    const s = stats as { total_samples: number; positive_count: number; negative_count: number; avg_prediction: number; accuracy: number; model_updates: number; model_version: string; ready: boolean; progress_pct: number };
                    const fillColor = s.ready
                      ? "bg-[var(--accent-positive)]"
                      : s.progress_pct > 50
                        ? "bg-[var(--accent-ink)]"
                        : "bg-[var(--text-muted)]";
                    const readyColor = s.ready
                      ? "text-[var(--accent-positive)]"
                      : "text-[var(--accent-warn)]";
                    return (
                      <div key={key} className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2.5 py-2">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-[10px] font-mono font-semibold text-[var(--text-strong)] uppercase">
                            {label}
                          </span>
                          <span className={`text-[10px] font-semibold ${readyColor}`}>
                            {s.ready ? "✓ Calibrated" : "⚠ Warming up"}
                          </span>
                        </div>
                        {/* Progress bar toward 30-sample threshold */}
                        <div className="h-1.5 rounded-full bg-[var(--line-subtle)] overflow-hidden mb-1.5">
                          <div
                            className={`h-full rounded-full ${fillColor} transition-all duration-500`}
                            style={{ width: `${Math.min(s.progress_pct, 100)}%` }}
                          />
                        </div>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]">
                          <span className="flex items-center gap-1">
                            <span className="text-[var(--text-label)]">Samples:</span>
                            <span className="font-mono font-semibold text-[var(--text-body)]">
                              {s.total_samples} / 30
                            </span>
                          </span>
                          <span className="flex items-center gap-1">
                            <span className="text-[var(--text-label)]">Accuracy:</span>
                            <span className="font-mono text-[var(--text-body)]">
                              {(s.accuracy * 100).toFixed(1)}%
                            </span>
                          </span>
                          <span className="flex items-center gap-1">
                            <span className="text-[var(--text-label)]">Updates:</span>
                            <span className="font-mono text-[var(--text-body)]">
                              {s.model_updates}
                            </span>
                          </span>
                        </div>
                        {/* Label distribution */}
                        <div className="mt-1.5 flex items-center gap-2">
                          <span className="text-[10px] text-[var(--text-label)]">Outcomes:</span>
                          <div className="flex-1 h-1 rounded-full bg-[var(--line-subtle)] overflow-hidden flex">
                            <div
                              className="h-full bg-[var(--accent-positive)]"
                              style={{ width: `${s.total_samples > 0 ? (s.positive_count / s.total_samples) * 100 : 50}%` }}
                            />
                            <div
                              className="h-full bg-[var(--accent-danger)]"
                              style={{ width: `${s.total_samples > 0 ? (s.negative_count / s.total_samples) * 100 : 50}%` }}
                            />
                          </div>
                          <span className="text-[10px] font-mono text-[var(--text-muted)]">
                            {s.positive_count}↑ / {s.negative_count}↓
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Model Persistence — Disk State */}
              {calibrationStats && Object.keys(calibrationStats).length > 0 && (
                <div className="space-y-2">
                  <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
                    Model Persistence
                  </p>
                  {Object.entries(calibrationStats).map(([key, stats]) => {
                    const label = key.replace(/_/g, " ").toUpperCase();
                    if (stats === null || ("error" in stats)) return null;
                    const s = stats as {
                      loaded_from_disk?: boolean;
                      save_count?: number;
                      brier_score?: number | null;
                      last_save_epoch?: number;
                      last_save_age_seconds?: number;
                      file_size_bytes?: number;
                    };
                    const loaded = s.loaded_from_disk ?? false;
                    const saveCount = s.save_count ?? 0;
                    const brier = s.brier_score;
                    const lastSaveAge = s.last_save_age_seconds ?? null;
                    const fileSize = s.file_size_bytes ?? 0;
                    if (!loaded && saveCount === 0) return null;
                    const brierColor =
                      brier === null || brier === undefined
                        ? "text-[var(--text-muted)]"
                        : brier <= 0.15
                          ? "text-[var(--accent-positive)]"
                          : brier <= 0.25
                            ? "text-[var(--accent-warn)]"
                            : "text-[var(--accent-danger)]";
                    const brierLabel =
                      brier === null || brier === undefined
                        ? "N/A"
                        : brier <= 0.15
                          ? "Good"
                          : brier <= 0.25
                            ? "Fair"
                            : "Poor";
                    const lastSaveStaleness = lastSaveAge !== null ? formatStaleness(Date.now() / 1000 - lastSaveAge) : null;
                    return (
                      <div key={key} className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2.5 py-2">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-[10px] font-mono font-semibold text-[var(--text-strong)] uppercase">
                            {label}
                          </span>
                          <span className={`text-[10px] font-semibold ${loaded ? "text-[var(--accent-positive)]" : "text-[var(--text-muted)]"}`}>
                            {loaded ? "✓ Restored from disk" : "Fresh model"}
                          </span>
                        </div>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]">
                          <span className="flex items-center gap-1">
                            <span className="text-[var(--text-label)]">Saved:</span>
                            <span className="font-mono font-semibold text-[var(--text-body)]">
                              {saveCount}×
                            </span>
                          </span>
                          {lastSaveStaleness && (
                            <span className="flex items-center gap-1">
                              <span className="text-[var(--text-label)]">Last save:</span>
                              <span className="font-mono text-[var(--text-body)]">
                                {lastSaveStaleness}
                              </span>
                            </span>
                          )}
                          <span className="flex items-center gap-1">
                            <span className="text-[var(--text-label)]">Brier:</span>
                            <span className={`font-mono font-semibold ${brierColor}`}>
                              {brier !== null && brier !== undefined ? brier.toFixed(3) : "—"}
                              <span className="text-[var(--text-muted)] font-normal ml-0.5">
                                ({brierLabel})
                              </span>
                            </span>
                          </span>
                          {fileSize > 0 && (
                            <span className="flex items-center gap-1">
                              <span className="text-[var(--text-label)]">Size:</span>
                              <span className="font-mono text-[var(--text-muted)]">
                                {fileSize < 1024 ? `${fileSize}B` : `${(fileSize / 1024).toFixed(1)}KB`}
                              </span>
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
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
