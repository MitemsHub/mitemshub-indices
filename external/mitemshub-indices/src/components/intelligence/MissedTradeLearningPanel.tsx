"use client";

import React from "react";
import type { MissedTradeLearning } from "../../lib/contracts";

interface MissedTradeLearningPanelProps {
  data: MissedTradeLearning;
  loading?: boolean;
}

function SkeletonBlock() {
  return (
    <div className="surface rounded-[1.25rem] p-5">
      <div className="flex items-center gap-3 mb-4">
        <div className="loading-pulse" aria-hidden="true" />
        <p className="text-sm text-[var(--text-muted)]">Loading missed trade data…</p>
      </div>
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-10 rounded-lg bg-[var(--bg-panel-muted)] animate-pulse" />
        ))}
      </div>
    </div>
  );
}

function StatCard({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="info-card rounded-xl p-3 text-center">
      <div className={`text-lg font-semibold ${accent || "text-[var(--text-strong)]"}`}>
        {value}
      </div>
      <div className="text-[0.7rem] uppercase tracking-wider text-[var(--text-muted)] mt-0.5">
        {label}
      </div>
    </div>
  );
}

export function MissedTradeLearningPanel({ data, loading }: MissedTradeLearningPanelProps) {
  if (loading) return <SkeletonBlock />;
  if (!data) {
    return (
      <div className="surface rounded-[1.25rem] p-5">
        <h3 className="text-sm font-semibold text-[var(--text-strong)] mb-2">
          Missed Trade Learning
        </h3>
        <p className="text-sm text-[var(--text-muted)]">
          No missed trade data available yet. The engine will start learning once NO_TRADE decisions are recorded.
        </p>
      </div>
    );
  }

  const isNoData = data.status === "no_data";
  const highMissRate = data.miss_rate > 0.4;
  const moderateMissRate = data.miss_rate > 0.2;

  return (
    <div className="surface rounded-[1.25rem] p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-strong)]">
            Missed Trade Learning
          </h3>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            Engine feedback from NO_TRADE decisions
          </p>
        </div>
        <div
          className={`status-badge ${
            data.status === "active" && highMissRate
              ? "status-badge--failing"
              : data.status === "active" && moderateMissRate
              ? "status-badge--confirmed"
              : "info-chip"
          }`}
        >
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              isNoData
                ? "bg-[var(--text-muted)]"
                : highMissRate
                ? "bg-[var(--accent-danger)]"
                : data.status === "active"
                ? "bg-[var(--accent-positive)]"
                : "bg-[var(--text-muted)]"
            }`}
          />
          {isNoData ? "No data" : highMissRate ? "Learning fast" : "Well calibrated"}
        </div>
      </div>

      {/* Insight */}
      <div
        className={`rounded-lg p-3 mb-4 text-sm ${
          highMissRate
            ? "bg-[var(--accent-danger-soft)] border border-[rgba(196,68,58,0.15)] text-[var(--accent-danger)]"
            : moderateMissRate
            ? "bg-[var(--accent-warn-soft)] border border-[rgba(184,134,11,0.15)] text-[var(--accent-warn)]"
            : "bg-[var(--accent-positive-soft)] border border-[rgba(15,107,87,0.15)] text-[var(--accent-positive)]"
        }`}
      >
        {data.insight}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <StatCard
          label="Miss Rate"
          value={data.miss_rate_display}
          accent={
            highMissRate
              ? "text-[var(--accent-danger)]"
              : moderateMissRate
              ? "text-[var(--accent-warn)]"
              : "text-[var(--accent-positive)]"
          }
        />
        <StatCard label="Missed" value={String(data.missed_opportunities)} accent="text-[var(--accent-danger)]" />
        <StatCard label="Correct" value={String(data.correct_stayouts)} accent="text-[var(--accent-positive)]" />
        <StatCard label="Pending" value={String(data.pending_count)} />
      </div>

      {/* Range Miss Boost */}
      {data.range_miss_boost > 0 && (
        <div className="rounded-lg bg-[var(--accent-ink-soft)] border border-[rgba(31,75,153,0.15)] p-3 mb-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[var(--accent-ink)]">
              Range-Bound Confidence Boost
            </span>
            <span className="text-sm font-semibold text-[var(--accent-ink)]">
              +{data.range_miss_boost_display}
            </span>
          </div>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            The engine has increased its willingness to trade range-bound markets due to missed opportunities.
          </p>
        </div>
      )}

      {/* Recent Outcomes Table */}
      {data.recent_outcomes.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider mb-2">
            Recent Outcomes (newest first)
          </h4>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--line-subtle)]">
                  <th className="text-left py-1.5 px-2 text-[var(--text-muted)] font-medium">Time</th>
                  <th className="text-left py-1.5 px-2 text-[var(--text-muted)] font-medium">Symbol</th>
                  <th className="text-left py-1.5 px-2 text-[var(--text-muted)] font-medium">Prediction</th>
                  <th className="text-left py-1.5 px-2 text-[var(--text-muted)] font-medium">Regime</th>
                  <th className="text-left py-1.5 px-2 text-[var(--text-muted)] font-medium">Outcome</th>
                  <th className="text-right py-1.5 px-2 text-[var(--text-muted)] font-medium">Move (ATR)</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_outcomes.slice(0, 20).map((outcome, idx) => (
                  <tr
                    key={idx}
                    className="border-b border-[var(--line-subtle)] last:border-0 hover:bg-[var(--bg-surface-hover)]"
                  >
                    <td className="py-1.5 px-2 text-[var(--text-body)] whitespace-nowrap">
                      {outcome.recorded_at
                        ? new Date(outcome.recorded_at).toLocaleString(undefined, {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "—"}
                    </td>
                    <td className="py-1.5 px-2 text-[var(--text-body)]">{outcome.symbol}</td>
                    <td className="py-1.5 px-2">
                      <span
                        className={
                          outcome.model_prediction === "long"
                            ? "text-[var(--accent-positive)]"
                            : outcome.model_prediction === "short"
                            ? "text-[var(--accent-danger)]"
                            : "text-[var(--text-muted)]"
                        }
                      >
                        {outcome.model_prediction}
                      </span>
                    </td>
                    <td className="py-1.5 px-2 text-[var(--text-body)]">{outcome.regime}</td>
                    <td className="py-1.5 px-2">
                      <span
                        className={`inline-flex items-center gap-1 ${
                          outcome.outcome === "missed_opportunity"
                            ? "text-[var(--accent-danger)]"
                            : "text-[var(--accent-positive)]"
                        }`}
                      >
                        <span
                          className={`inline-block w-1.5 h-1.5 rounded-full ${
                            outcome.outcome === "missed_opportunity"
                              ? "bg-[var(--accent-danger)]"
                              : "bg-[var(--accent-positive)]"
                          }`}
                        />
                        {outcome.outcome === "missed_opportunity" ? "Missed" : "Correct"}
                      </span>
                    </td>
                    <td className="py-1.5 px-2 text-right text-[var(--text-body)] font-mono">
                      {outcome.price_move_atr != null ? `${outcome.price_move_atr.toFixed(2)}×` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
