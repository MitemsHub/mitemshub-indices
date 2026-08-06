import React, { useCallback, useEffect, useState } from "react";
import type { FreshCallResponse } from "../../lib/contracts";
import {
  formatCallHeadline,
  formatGuardianState,
  formatMarketCopy,
  formatPrice,
  formatSymbol,
  formatTimestamp,
} from "../../lib/formatters";

type HistoryPanelProps = {
  history: FreshCallResponse[];
};

/** Signal feedback record fetched from /api/feedback */
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
};

function OutcomeBadge({ outcome }: { outcome: string | null }) {
  if (!outcome) return <span className="text-[10px] text-[var(--text-muted)]">Pending</span>;
  const config: Record<string, { label: string; cls: string }> = {
    tp_hit: { label: "TP ✓", cls: "bg-emerald-50 text-emerald-700 border border-emerald-200" },
    sl_hit: { label: "SL ✗", cls: "bg-rose-50 text-rose-700 border border-rose-200" },
    expired: { label: "Expired", cls: "bg-gray-50 text-gray-500 border border-gray-200" },
    manual_win: { label: "Win ✓", cls: "bg-emerald-50 text-emerald-700 border border-emerald-200" },
    manual_loss: { label: "Loss ✗", cls: "bg-rose-50 text-rose-700 border border-rose-200" },
  };
  const c = config[outcome] ?? { label: outcome, cls: "bg-gray-50 text-gray-500 border border-gray-200" };
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${c.cls}`}>{c.label}</span>;
}

function FeedbackButtons({
  signalId,
  currentFeedback,
  onFeedback,
}: {
  signalId: string;
  currentFeedback: string | null;
  onFeedback: (signalId: string, feedback: string) => void;
}) {
  if (currentFeedback) {
    const emoji = currentFeedback === "good" ? "👍" : currentFeedback === "bad" ? "👎" : "⏭️";
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-[var(--text-muted)]">
        {emoji} {currentFeedback === "good" ? "Good call" : currentFeedback === "bad" ? "Bad call" : "Skipped"}
      </span>
    );
  }

  return (
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        onClick={() => onFeedback(signalId, "good")}
        className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700 transition hover:bg-emerald-100 hover:scale-105 active:scale-95"
        title="This was a good call"
      >
        👍 Good
      </button>
      <button
        type="button"
        onClick={() => onFeedback(signalId, "bad")}
        className="rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[10px] font-medium text-rose-700 transition hover:bg-rose-100 hover:scale-105 active:scale-95"
        title="This was a bad call"
      >
        👎 Bad
      </button>
      <button
        type="button"
        onClick={() => onFeedback(signalId, "skipped")}
        className="rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[10px] font-medium text-gray-500 transition hover:bg-gray-100 hover:scale-105 active:scale-95"
        title="I skipped this trade"
      >
        ⏭️
      </button>
    </div>
  );
}

function HistoryEntry({
  entry,
  feedback,
  onFeedback,
}: {
  entry: FreshCallResponse;
  feedback: SignalFeedback | null;
  onFeedback: (signalId: string, feedback: string) => void;
}) {
  const isStandAside = entry.call === "stand_aside";
  const isBuy = entry.call === "buy_candidate";
  const signalId = `${entry.symbol}_${entry.generated_at.replace(/:/g, "-").replace(/\./g, "-")}`;
  // A failing/cancelled plan's old levels are invalid — never show them.
  const isStaleEntry =
    entry.guardian_state === "failing" || entry.guardian_state === "cancelled";
  const hasExecutionLevels =
    entry.entry !== null &&
    entry.entry !== undefined &&
    !isStaleEntry;

  return (
    <article className="rounded-xl border border-[var(--line-subtle)] bg-[var(--bg-panel-strong)] p-4 transition hover:shadow-[0_8px_24px_rgba(22,29,45,0.04)]">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            className={`pulse-dot ${
              isStandAside ? "pulse-dot--muted" :
              isBuy ? "pulse-dot--positive" :
              "pulse-dot--danger"
            }`}
            aria-hidden="true"
          />
          <p className="text-sm font-medium text-[var(--text-strong)]">{formatSymbol(entry.symbol)}</p>
        </div>
        <p className="text-xs text-[var(--text-muted)]">{formatTimestamp(entry.generated_at)}</p>
      </div>
      <p className="mt-1.5 text-sm font-medium text-[var(--text-body)]">
        {formatCallHeadline(entry.call)}
      </p>
      {entry.trade_status !== "not_valid" && (
        <span className={`status-badge mt-2 ${
          entry.guardian_state === "confirmed" ? "status-badge--confirmed" :
          entry.guardian_state === "actionable" ? "status-badge--actionable" :
          entry.guardian_state === "failing" ? "status-badge--failing" :
          entry.guardian_state === "cancelled" ? "status-badge--cancelled" :
          "status-badge--forming"
        }`}>
          {formatGuardianState(entry.guardian_state)}
        </span>
      )}

      {/* Execution levels summary */}
      {hasExecutionLevels && (
        <div className="mt-2 flex items-center gap-3 text-[10px] tabular-nums">
          <span className="text-[var(--text-muted)]">Entry <span className="font-semibold text-[var(--text-strong)]">{formatPrice(entry.entry)}</span></span>
          {entry.execution_stop && <span className="text-[var(--text-muted)]">SL <span className="font-semibold text-[var(--accent-danger)]">{formatPrice(entry.execution_stop)}</span></span>}
          {entry.primary_target && <span className="text-[var(--text-muted)]">TP <span className="font-semibold text-[var(--accent-positive)]">{formatPrice(entry.primary_target)}</span></span>}
        </div>
      )}

      <p className="mt-2 text-xs leading-5 text-[var(--text-muted)]">
        {formatMarketCopy(entry.why)}
      </p>

      {/* Feedback section */}
      <div className="mt-3 flex items-center justify-between border-t border-[var(--line-subtle)] pt-3">
        <FeedbackButtons
          signalId={signalId}
          currentFeedback={feedback?.user_feedback ?? null}
          onFeedback={onFeedback}
        />
        {feedback?.outcome && (
          <div className="flex items-center gap-2">
            <OutcomeBadge outcome={feedback.outcome} />
            {feedback.r_multiple != null && (
              <span className={`text-[10px] font-semibold tabular-nums ${
                feedback.r_multiple > 0 ? "text-[var(--accent-positive)]" : feedback.r_multiple < 0 ? "text-[var(--accent-danger)]" : "text-[var(--text-muted)]"
              }`}>
                {feedback.r_multiple > 0 ? "+" : ""}{feedback.r_multiple.toFixed(1)}R
              </span>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

export function HistoryPanel({ history }: HistoryPanelProps) {
  const [feedbackMap, setFeedbackMap] = useState<Map<string, SignalFeedback>>(new Map());

  // Load feedback data on mount and when history changes
  useEffect(() => {
    async function loadFeedback() {
      try {
        const response = await fetch("/api/feedback?limit=50");
        if (response.ok) {
          const data = await response.json();
          const map = new Map<string, SignalFeedback>();
          for (const sig of data.signals ?? []) {
            map.set(sig.signal_id, sig);
          }
          setFeedbackMap(map);
        }
      } catch {
        // Keep empty map on failure
      }
    }
    void loadFeedback();
  }, [history]);

  const handleFeedback = useCallback(async (signalId: string, feedback: string) => {
    try {
      const response = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "record_feedback",
          signal_id: signalId,
          feedback,
        }),
      });
      if (response.ok) {
        // Update local state immediately
        setFeedbackMap((prev) => {
          const next = new Map(prev);
          const existing = next.get(signalId);
          if (existing) {
            next.set(signalId, {
              ...existing,
              user_feedback: feedback,
              feedback_at: new Date().toISOString(),
            });
          }
          return next;
        });
      }
    } catch {
      // Best effort — feedback is non-critical
    }
  }, []);

  return (
    <section className="rounded-2xl border border-[var(--line-subtle)] bg-[rgba(248,250,252,0.82)] px-5 py-5 shadow-[var(--shadow-card)]">
      <div className="flex items-center justify-between">
        <div>
          <p className="utility-copy text-[11px] uppercase tracking-[0.24em] text-[var(--text-label)]">
            Recent decisions
          </p>
          <h3 className="display-serif mt-2 text-lg font-semibold text-[var(--text-strong)]">
            Recent trade plans
          </h3>
        </div>
        <p className="text-[10px] text-[var(--text-muted)]">
          Rate calls to help the system learn
        </p>
      </div>

      <div className="mt-4 space-y-3">
        {history.length > 0 ? (
          history.map((entry, index) => {
            const signalId = `${entry.symbol}_${entry.generated_at.replace(/:/g, "-").replace(/\./g, "-")}`;
            return (
              <HistoryEntry
                key={`${index}-${entry.symbol}-${entry.generated_at}`}
                entry={entry}
                feedback={feedbackMap.get(signalId) ?? null}
                onFeedback={handleFeedback}
              />
            );
          })
        ) : (
          <div className="rounded-xl border border-[var(--line-subtle)] bg-white/78 p-5 text-center">
            <div className="pulse-dot pulse-dot--muted mx-auto mb-2" aria-hidden="true" />
            <p className="text-sm leading-6 text-[var(--text-muted)]">
              Recent live decisions appear here after you pull a fresh market read.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
