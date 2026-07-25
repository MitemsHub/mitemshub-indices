"use client"

import type { RiskAssessment } from "../../lib/contracts";
import { formatPct, formatNumber } from "../../lib/formatters";

type RiskAssessmentPanelProps = {
  assessment: RiskAssessment | null;
};

export function RiskAssessmentPanel({ assessment }: RiskAssessmentPanelProps) {
  if (!assessment) {
    return (
      <section className="intelligence-panel surface rounded-[1.5rem] p-4">
        <p className="utility-copy text-xs uppercase tracking-[0.2em]">Risk Assessment</p>
        <p className="mt-4 text-base text-[var(--text-body)]">No risk data available.</p>
      </section>
    );
  }

  const drawdownPct = (assessment.current_drawdown / assessment.max_drawdown_limit) * 100;
  const drawdownStatus = drawdownPct > 70 ? "critical" : drawdownPct > 40 ? "warning" : "good";

  return (
    <section className="intelligence-panel surface rounded-[1.5rem] p-4">
      <div className="flex items-center justify-between">
        <p className="utility-copy text-xs uppercase tracking-[0.2em]">Risk Assessment</p>
        <span className={`info-chip rounded-full px-3 py-1 text-sm font-medium ${
          drawdownStatus === "critical" ? "text-[var(--accent-danger)] bg-[var(--accent-danger-soft)]" :
          drawdownStatus === "warning" ? "text-[var(--accent-warn)] bg-[var(--accent-warn-soft)]" :
          "text-[var(--accent-positive)] bg-[var(--accent-positive-soft)]"
        }`}>
          {drawdownStatus === "critical" ? "High Risk" : drawdownStatus === "warning" ? "Elevated Risk" : "Low Risk"}
        </span>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <RiskMetricCard
          title="Risk per Trade"
          value={`${(assessment.risk_per_trade * 100).toFixed(2)}%`}
          target={`Max ${formatPct(assessment.max_daily_loss)} daily`}
          status={assessment.risk_per_trade <= 0.01 ? "good" : "warning"}
        />
        <RiskMetricCard
          title="Daily PnL"
          value={formatNumber(assessment.current_daily_pnl, 2)}
          target={`Limit: ${formatPct(assessment.max_daily_loss)}`}
          status={assessment.current_daily_pnl > -assessment.max_daily_loss * 0.5 ? "good" : assessment.current_daily_pnl > -assessment.max_daily_loss ? "warning" : "critical"}
        />
        <RiskMetricCard
          title="Consecutive Losses"
          value={assessment.consecutive_losses.toString()}
          target={`Max: ${assessment.max_consecutive_losses}`}
          status={assessment.consecutive_losses < assessment.max_consecutive_losses * 0.5 ? "good" : assessment.consecutive_losses < assessment.max_consecutive_losses ? "warning" : "critical"}
        />
        <RiskMetricCard
          title="Drawdown"
          value={`${assessment.current_drawdown.toFixed(2)}%`}
          target={`Limit: ${assessment.max_drawdown_limit.toFixed(2)}%`}
          status={drawdownStatus}
        />
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <DetailCard
          title="Position Size"
          value={`${(assessment.position_size * 100).toFixed(2)}%`}
          hint={`Max: ${(assessment.max_position_size * 100).toFixed(2)}%`}
        />
        <DetailCard
          title="Current Drawdown"
          value={`${assessment.current_drawdown.toFixed(2)}%`}
          hint={`Limit: ${assessment.max_drawdown_limit.toFixed(2)}%`}
        />
      </div>

      <div className="mt-4 p-4 rounded-lg bg-[var(--accent-neutral-soft)] border border-[var(--accent-neutral-soft)]">
        <p className="utility-copy text-xs uppercase tracking-[0.2em] text-[var(--accent-neutral)] mb-2">Risk Parameters</p>
        <div className="grid gap-2 md:grid-cols-3 text-sm">
          <div>
            <p className="text-[var(--accent-neutral)]">Max Daily Loss</p>
            <p className="font-medium" style={{ color: "var(--text-strong)" }}>{formatPct(assessment.max_daily_loss)}</p>
          </div>
          <div>
            <p className="text-[var(--accent-neutral)]">Max Consecutive Losses</p>
            <p className="font-medium" style={{ color: "var(--text-strong)" }}>{assessment.max_consecutive_losses}</p>
          </div>
          <div>
            <p className="text-[var(--accent-neutral)]">Risk per Trade</p>
            <p className="font-medium" style={{ color: "var(--text-strong)" }}>{formatPct(assessment.risk_per_trade)}</p>
          </div>
        </div>
      </div>

      {drawdownStatus === "critical" && (
        <div className="mt-4 p-4 rounded-lg bg-[var(--accent-danger-soft)] border border-[var(--accent-danger-soft)]">
          <p className="utility-copy text-xs uppercase tracking-[0.2em] text-[var(--accent-danger)] mb-2">⚠ High Risk Alert</p>
          <p className="text-sm" style={{ color: "var(--accent-danger)" }}>Drawdown exceeds 70% of limit. Consider reducing position size or pausing trading.</p>
        </div>
      )}
    </section>
  );
}

function RiskMetricCard({
  title,
  value,
  target,
  status,
}: {
  title: string;
  value: string;
  target: string;
  status: "good" | "warning" | "critical";
}) {
  const statusColors: Record<string, string> = {
    good: "text-[var(--accent-positive)] bg-[var(--accent-positive-soft)] border-[var(--accent-positive-soft)]",
    warning: "text-[var(--accent-warn)] bg-[var(--accent-warn-soft)] border-[var(--accent-warn-soft)]",
    critical: "text-[var(--accent-danger)] bg-[var(--accent-danger-soft)] border-[var(--accent-danger-soft)]",
  };

  const statusLabels = { good: "✓ OK", warning: "⚠ Watch", critical: "⚠ Critical" };

  return (
    <div className={`info-card rounded-[1rem] p-4 ${statusColors[status]}`}>
      <p className="utility-copy text-xs uppercase tracking-[0.2em] text-[var(--accent-neutral)] mb-2">{title}</p>
      <p className="text-lg font-semibold" style={{ color: "var(--text-strong)" }}>{value}</p>
      <p className="mt-1 text-xs text-[var(--accent-neutral)]">{target}</p>
      <div className="mt-2 flex items-center gap-1">
        <span className={`info-chip rounded-full px-2 py-0.5 text-xs ${statusColors[status]}`}>
          {statusLabels[status]}
        </span>
      </div>
    </div>
  );
}

function DetailCard({ title, value, hint }: { title: string; value: string; hint?: string }) {
  return (
    <div className="info-card rounded-[1rem] p-4">
      <p className="utility-copy text-xs uppercase tracking-[0.2em] text-[var(--text-label)]">{title}</p>
      <p className="mt-2 text-base font-semibold text-[var(--text-strong)]">{value}</p>
      {hint && <p className="mt-1 text-xs text-[var(--text-muted)]">{hint}</p>}
    </div>
  );
}
