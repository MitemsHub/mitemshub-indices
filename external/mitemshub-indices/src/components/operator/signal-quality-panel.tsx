"use client";

import React, { useEffect, useState, useCallback } from "react";

type SignalFeedback = {
  signal_id: string;
  symbol: string;
  direction: string;
  generated_at: string;
  entry: number;
  stop_loss: number;
  take_profit: number;
  confidence: number;
  regime: string;
  signal_strength: string;
  user_feedback: string | null;
  feedback_at: string | null;
  feedback_notes: string | null;
  outcome: string | null;
  outcome_price: number | null;
  outcome_at: string | null;
  pnl_pips: number | null;
  r_multiple: number | null;
  fed_to_calibration: boolean;
  fed_at: string | null;
};

type FeedbackStats = {
  total: number;
  resolved: number;
  pending: number;
  tp_hits: number;
  sl_hits: number;
  win_rate: number;
  with_feedback: number;
  good_feedback: number;
  bad_feedback: number;
  pending_feedback: number;
};

type FeedbackResponse = {
  signals: SignalFeedback[];
  stats: FeedbackStats;
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

function ScoreBar({ value, max = 1, color }: { value: number; max?: number; color: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className="h-1.5 rounded-full bg-[var(--line-subtle)] overflow-hidden">
      <div
        className={`h-full rounded-full ${color} transition-all duration-500`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function StatCard({
  label,
  value,
  subtitle,
  color,
}: {
  label: string;
  value: string;
  subtitle?: string;
  color?: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] px-2.5 py-2">
      <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium mb-1">
        {label}
      </p>
      <p className={`text-lg font-bold font-mono ${color || "text-[var(--text-strong)]"}`}>
        {value}
      </p>
      {subtitle && (
        <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{subtitle}</p>
      )}
    </div>
  );
}

export function SignalQualityPanel() {
  const [data, setData] = useState<FeedbackResponse | null>(null);
  const [fetchError, setFetchError] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch("/api/feedback?limit=100");
      if (!res.ok) throw new Error("Non-ok response");
      const result = (await res.json()) as FeedbackResponse;
      setData(result);
      setFetchError(false);
    } catch {
      setFetchError(true);
    }
  }, []);

  useEffect(() => {
    void fetchData();
    const interval = setInterval(() => void fetchData(), 15_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const stats = data?.stats;
  const signals = data?.signals || [];

  // Compute average R-multiple from resolved signals
  const resolvedSignals = signals.filter(
    (s) => s.outcome !== null && s.r_multiple !== null,
  );
  const avgRMultiple =
    resolvedSignals.length > 0
      ? resolvedSignals.reduce((sum, s) => sum + (s.r_multiple || 0), 0) /
        resolvedSignals.length
      : 0;

  // Compute calibration-fed count
  const fedCount = signals.filter((s) => s.fed_to_calibration).length;

  // Win rate color
  const winRateColor =
    !stats || stats.resolved === 0
      ? "text-[var(--text-muted)]"
      : stats.win_rate >= 0.55
        ? "text-[var(--accent-positive)]"
        : stats.win_rate >= 0.45
          ? "text-[var(--text-strong)]"
          : "text-[var(--accent-danger)]";

  // R-multiple color
  const rMultipleColor =
    resolvedSignals.length === 0
      ? "text-[var(--text-muted)]"
      : avgRMultiple > 0
        ? "text-[var(--accent-positive)]"
        : avgRMultiple < 0
          ? "text-[var(--accent-danger)]"
          : "text-[var(--text-strong)]";

  const hasData = stats && stats.total > 0;

  return (
    <div className="surface rounded-xl mt-2">
      {/* Toggle header */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-[11px] text-[var(--text-muted)] hover:text-[var(--text-body)] transition-colors"
        aria-expanded={expanded}
        aria-label="Toggle signal quality"
      >
        <span className="flex items-center gap-2">
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              fetchError
                ? "bg-[var(--accent-danger)]"
                : hasData && (stats?.resolved ?? 0) > 0
                  ? "bg-[var(--accent-positive)]"
                  : "bg-[var(--text-muted)]"
            }`}
            aria-hidden="true"
          />
          <span className="font-medium tracking-wide uppercase">
            Signal Quality
          </span>
          {!expanded && stats && (
            <span className="text-[10px] text-[var(--text-muted)]">
              {stats.resolved > 0
                ? `${(stats.win_rate * 100).toFixed(0)}% WR · ${stats.resolved} resolved`
                : `${stats.total} tracked · ${stats.pending} pending`}
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
              Signal quality data unavailable. Run a live call to populate.
            </p>
          ) : !stats ? (
            <div className="flex items-center gap-2 text-[11px] text-[var(--text-muted)]">
              <div className="w-2 h-2 rounded-full bg-[var(--line-subtle)] animate-pulse" />
              Loading signal quality...
            </div>
          ) : (
            <>
              {/* Summary stats grid */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                <StatCard
                  label="Win Rate"
                  value={stats.resolved > 0 ? `${(stats.win_rate * 100).toFixed(1)}%` : "—"}
                  subtitle={`${stats.tp_hits}W / ${stats.sl_hits}L`}
                  color={winRateColor}
                />
                <StatCard
                  label="Avg R-Multiple"
                  value={resolvedSignals.length > 0 ? avgRMultiple.toFixed(2) : "—"}
                  subtitle={`${resolvedSignals.length} resolved`}
                  color={rMultipleColor}
                />
                <StatCard
                  label="Fed to Calibration"
                  value={`${fedCount}`}
                  subtitle={`of ${stats.total} signals`}
                  color="text-[var(--accent-ink)]"
                />
                <StatCard
                  label="Pending"
                  value={`${stats.pending}`}
                  subtitle={`${stats.pending_feedback} awaiting feedback`}
                  color={
                    stats.pending > 0 ? "text-[var(--accent-warn)]" : "text-[var(--accent-positive)]"
                  }
                />
              </div>

              {/* Win rate bar */}
              {stats.resolved > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
                    Win Rate
                  </p>
                  <div className="flex items-center gap-3">
                    <div className="flex-1">
                      <ScoreBar
                        value={stats.win_rate}
                        max={1}
                        color={
                          stats.win_rate >= 0.55
                            ? "bg-[var(--accent-positive)]"
                            : stats.win_rate >= 0.45
                              ? "bg-[var(--accent-ink)]"
                              : "bg-[var(--accent-danger)]"
                        }
                      />
                    </div>
                    <span className="text-[11px] font-mono font-semibold text-[var(--text-body)]">
                      {(stats.win_rate * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              )}

              {/* Feedback distribution */}
              {stats.with_feedback > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
                    Feedback Distribution
                  </p>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-2 rounded-full bg-[var(--line-subtle)] overflow-hidden flex">
                      <div
                        className="h-full bg-[var(--accent-positive)]"
                        style={{
                          width: `${(stats.good_feedback / Math.max(stats.with_feedback, 1)) * 100}%`,
                        }}
                      />
                      <div
                        className="h-full bg-[var(--accent-danger)]"
                        style={{
                          width: `${(stats.bad_feedback / Math.max(stats.with_feedback, 1)) * 100}%`,
                        }}
                      />
                    </div>
                    <span className="text-[10px] font-mono text-[var(--text-muted)]">
                      {stats.good_feedback}👍 / {stats.bad_feedback}👎
                    </span>
                  </div>
                </div>
              )}

              {/* Recent signals table */}
              {signals.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[10px] uppercase tracking-[0.16em] text-[var(--text-label)] font-medium">
                    Recent Signals
                  </p>
                  <div className="rounded-lg border border-[var(--line-subtle)] bg-[var(--bg-panel-muted)] overflow-hidden">
                    <div className="max-h-48 overflow-y-auto">
                      <table className="w-full text-[10px]">
                        <thead>
                          <tr className="border-b border-[var(--line-subtle)]">
                            <th className="px-2 py-1.5 text-left text-[var(--text-label)] font-medium">
                              Time
                            </th>
                            <th className="px-2 py-1.5 text-left text-[var(--text-label)] font-medium">
                              Sym
                            </th>
                            <th className="px-2 py-1.5 text-left text-[var(--text-label)] font-medium">
                              Dir
                            </th>
                            <th className="px-2 py-1.5 text-left text-[var(--text-label)] font-medium">
                              Outcome
                            </th>
                            <th className="px-2 py-1.5 text-right text-[var(--text-label)] font-medium">
                              R
                            </th>
                            <th className="px-2 py-1.5 text-right text-[var(--text-label)] font-medium">
                              Fed
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {signals.slice(0, 15).map((s) => {
                            const outcomeColor =
                              s.outcome === "tp_hit" || s.outcome === "manual_win"
                                ? "text-[var(--accent-positive)]"
                                : s.outcome === "sl_hit" || s.outcome === "manual_loss"
                                  ? "text-[var(--accent-danger)]"
                                  : s.outcome === "expired"
                                    ? "text-[var(--text-muted)]"
                                    : "text-[var(--accent-warn)]";
                            const outcomeLabel =
                              s.outcome === "tp_hit"
                                ? "TP ✓"
                                : s.outcome === "sl_hit"
                                  ? "SL ✗"
                                  : s.outcome === "manual_win"
                                    ? "Win"
                                    : s.outcome === "manual_loss"
                                      ? "Loss"
                                      : s.outcome === "expired"
                                        ? "Expired"
                                        : "Pending";
                            return (
                              <tr
                                key={s.signal_id}
                                className="border-b border-[var(--line-subtle)] last:border-b-0"
                              >
                                <td className="px-2 py-1.5 font-mono text-[var(--text-body)]">
                                  {formatTimestamp(s.generated_at)}
                                </td>
                                <td className="px-2 py-1.5 font-mono text-[var(--text-body)]">
                                  {s.symbol.replace("R_", "V")}
                                </td>
                                <td className="px-2 py-1.5">
                                  <span
                                    className={
                                      s.direction === "buy"
                                        ? "text-[var(--accent-positive)]"
                                        : "text-[var(--accent-danger)]"
                                    }
                                  >
                                    {s.direction === "buy" ? "▲" : "▼"}
                                  </span>
                                </td>
                                <td className={`px-2 py-1.5 font-semibold ${outcomeColor}`}>
                                  {outcomeLabel}
                                </td>
                                <td className="px-2 py-1.5 text-right font-mono">
                                  {s.r_multiple !== null ? (
                                    <span
                                      className={
                                        s.r_multiple > 0
                                          ? "text-[var(--accent-positive)]"
                                          : s.r_multiple < 0
                                            ? "text-[var(--accent-danger)]"
                                            : "text-[var(--text-muted)]"
                                      }
                                    >
                                      {s.r_multiple.toFixed(2)}
                                    </span>
                                  ) : (
                                    <span className="text-[var(--text-muted)]">—</span>
                                  )}
                                </td>
                                <td className="px-2 py-1.5 text-right">
                                  {s.fed_to_calibration ? (
                                    <span className="text-[var(--accent-positive)]">✓</span>
                                  ) : (
                                    <span className="text-[var(--text-muted)]">—</span>
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}

              {/* Empty state */}
              {stats.total === 0 && (
                <p className="text-[11px] text-[var(--text-muted)] italic text-center py-2">
                  No signals tracked yet. Execute a trade to start learning.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
