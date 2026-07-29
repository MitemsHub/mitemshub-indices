"use client";

import { useState } from "react";
import type { CurveFittingTest } from "../../lib/contracts";

interface Props {
  data: NonNullable<CurveFittingTest>;
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const isGood = verdict.includes("GENUINE EDGE");
  const isWeak = verdict.includes("WEAK EDGE") || verdict.includes("LIKELY EDGE");
  const isBad = verdict.includes("NO EDGE") || verdict.includes("CURVE-FITTED");

  return (
    <span
      className="status-badge"
      style={{
        background: isGood
          ? "rgba(15, 107, 87, 0.12)"
          : isWeak
          ? "rgba(184, 134, 11, 0.12)"
          : isBad
          ? "rgba(196, 68, 58, 0.12)"
          : "rgba(100, 116, 139, 0.1)",
        color: isGood
          ? "var(--accent-positive)"
          : isWeak
          ? "var(--accent-warn)"
          : isBad
          ? "var(--accent-danger)"
          : "var(--text-muted)",
        border: `1px solid ${
          isGood
            ? "rgba(15, 107, 87, 0.2)"
            : isWeak
            ? "rgba(184, 134, 11, 0.2)"
            : isBad
            ? "rgba(196, 68, 58, 0.2)"
            : "rgba(100, 116, 139, 0.15)"
        }`,
        fontWeight: 600,
        fontSize: "0.8125rem",
      }}
    >
      {verdict}
    </span>
  );
}

function MetricCard({
  label,
  value,
  subtitle,
  color,
}: {
  label: string;
  value: string | number;
  subtitle?: string;
  color?: string;
}) {
  return (
    <div
      className="info-card"
      style={{
        padding: "0.75rem 1rem",
        borderRadius: "0.5rem",
        minWidth: 0,
      }}
    >
      <div
        className="utility-copy"
        style={{ fontSize: "0.6875rem", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: "0.25rem" }}
      >
        {label}
      </div>
      <div style={{ fontSize: "1.25rem", fontWeight: 700, color: color || "var(--text-strong)", lineHeight: 1.2 }}>
        {value}
      </div>
      {subtitle && (
        <div className="utility-copy" style={{ fontSize: "0.6875rem", marginTop: "0.125rem" }}>
          {subtitle}
        </div>
      )}
    </div>
  );
}

function ScoreBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min(100, (Math.abs(value) / max) * 100) : 0;
  return (
    <div style={{ width: "100%", height: "6px", borderRadius: "3px", background: "var(--line-subtle)", overflow: "hidden" }}>
      <div
        style={{
          width: `${pct}%`,
          height: "100%",
          borderRadius: "3px",
          background: color,
          transition: "width 400ms var(--ease-out)",
        }}
      />
    </div>
  );
}

export default function CurveFittingTestPanel({ data }: Props) {
  const [showEpisodes, setShowEpisodes] = useState(false);

  const { aggregate, consistency, curve_fitting, prop_firm, episodes, verdict, explanation } = data;

  const deflatedColor =
    curve_fitting.deflated_sharpe > 1.0
      ? "var(--accent-positive)"
      : curve_fitting.deflated_sharpe > 0
      ? "var(--accent-warn)"
      : "var(--accent-danger)";

  const pboColor =
    curve_fitting.pbo_score < 0.3
      ? "var(--accent-positive)"
      : curve_fitting.pbo_score < 0.5
      ? "var(--accent-warn)"
      : "var(--accent-danger)";

  const mcColor =
    curve_fitting.monte_carlo_p_value < 0.05
      ? "var(--accent-positive)"
      : curve_fitting.monte_carlo_p_value < 0.1
      ? "var(--accent-warn)"
      : "var(--text-muted)";

  const consistencyColor =
    consistency.consistency_score > 0.7
      ? "var(--accent-positive)"
      : consistency.consistency_score > 0.4
      ? "var(--accent-warn)"
      : "var(--accent-danger)";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      {/* Verdict banner */}
      <div
        style={{
          padding: "1rem 1.25rem",
          borderRadius: "0.75rem",
          background: curve_fitting.edge_detected
            ? "rgba(15, 107, 87, 0.06)"
            : "rgba(196, 68, 58, 0.06)",
          border: `1px solid ${
            curve_fitting.edge_detected ? "rgba(15, 107, 87, 0.15)" : "rgba(196, 68, 58, 0.15)"
          }`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.5rem" }}>
          <VerdictBadge verdict={verdict} />
        </div>
        <p style={{ margin: 0, fontSize: "0.8125rem", lineHeight: 1.5, color: "var(--text-body" }}>
          {explanation}
        </p>
        <div className="utility-copy" style={{ fontSize: "0.6875rem", marginTop: "0.5rem" }}>
          {data.n_episodes} episodes × {data.n_ticks_per_episode.toLocaleString()} ticks · Symbol: {data.symbol}
          {data.ran_at && ` · Last run: ${new Date(data.ran_at).toLocaleString()}`}
        </div>
      </div>

      {/* Key metrics grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "0.5rem" }}>
        <MetricCard
          label="Deflated Sharpe"
          value={curve_fitting.deflated_sharpe.toFixed(2)}
          subtitle={curve_fitting.deflated_sharpe > 1.0 ? "> 1.0 = good" : "< 1.0 = chance"}
          color={deflatedColor}
        />
        <MetricCard
          label="PBO Score"
          value={curve_fitting.pbo_score.toFixed(2)}
          subtitle={curve_fitting.pbo_score < 0.3 ? "Low overfitting" : curve_fitting.pbo_score < 0.5 ? "Moderate risk" : "High risk"}
          color={pboColor}
        />
        <MetricCard
          label="MC p-value"
          value={curve_fitting.monte_carlo_p_value.toFixed(4)}
          subtitle={curve_fitting.monte_carlo_p_value < 0.05 ? "Significant" : "Not significant"}
          color={mcColor}
        />
        <MetricCard
          label="Consistency"
          value={consistency.consistency_score.toFixed(2)}
          subtitle={`WR σ: ±${(consistency.win_rate_std * 100).toFixed(1)}%`}
          color={consistencyColor}
        />
      </div>

      {/* Aggregate performance */}
      <div>
        <h4
          style={{
            margin: "0 0 0.5rem 0",
            fontSize: "0.75rem",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: "var(--text-muted)",
          }}
        >
          Aggregate Performance
        </h4>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))", gap: "0.5rem" }}>
          <MetricCard
            label="Win Rate"
            value={`${(aggregate.mean_win_rate * 100).toFixed(1)}%`}
            subtitle={`±${(consistency.win_rate_std * 100).toFixed(1)}%`}
          />
          <MetricCard
            label="Profit Factor"
            value={aggregate.mean_profit_factor.toFixed(2)}
            subtitle={`±${consistency.profit_factor_std.toFixed(2)}`}
          />
          <MetricCard
            label="Expectancy"
            value={`${aggregate.mean_expectancy_r.toFixed(3)}R`}
          />
          <MetricCard
            label="Net PnL"
            value={aggregate.mean_net_pnl.toFixed(2)}
          />
          <MetricCard
            label="Signals/Ep"
            value={aggregate.mean_signals.toFixed(1)}
          />
        </div>
      </div>

      {/* Consistency bars */}
      <div>
        <h4
          style={{
            margin: "0 0 0.5rem 0",
            fontSize: "0.75rem",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: "var(--text-muted)",
          }}
        >
          Score Bars
        </h4>
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.25rem" }}>
              <span className="utility-copy" style={{ fontSize: "0.6875rem" }}>Deflated Sharpe</span>
              <span className="utility-copy" style={{ fontSize: "0.6875rem" }}>{curve_fitting.deflated_sharpe.toFixed(2)}</span>
            </div>
            <ScoreBar value={curve_fitting.deflated_sharpe} max={3} color={deflatedColor} />
          </div>
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.25rem" }}>
              <span className="utility-copy" style={{ fontSize: "0.6875rem" }}>PBO (lower = better)</span>
              <span className="utility-copy" style={{ fontSize: "0.6875rem" }}>{curve_fitting.pbo_score.toFixed(2)}</span>
            </div>
            <ScoreBar value={1 - curve_fitting.pbo_score} max={1} color={pboColor} />
          </div>
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.25rem" }}>
              <span className="utility-copy" style={{ fontSize: "0.6875rem" }}>Consistency</span>
              <span className="utility-copy" style={{ fontSize: "0.6875rem" }}>{consistency.consistency_score.toFixed(2)}</span>
            </div>
            <ScoreBar value={consistency.consistency_score} max={1} color={consistencyColor} />
          </div>
        </div>
      </div>

      {/* Prop firm breaches (if available) */}
      {prop_firm && prop_firm.total_breaches > 0 && (
        <div
          style={{
            padding: "0.75rem 1rem",
            borderRadius: "0.5rem",
            background: "rgba(184, 134, 11, 0.06)",
            border: "1px solid rgba(184, 134, 11, 0.15)",
          }}
        >
          <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--accent-warn)", marginBottom: "0.375rem" }}>
            ⚠️ {prop_firm.name} — {prop_firm.total_breaches} Total Breaches
          </div>
          <div className="utility-copy" style={{ fontSize: "0.6875rem", lineHeight: 1.5 }}>
            Daily loss: {prop_firm.daily_loss_breaches} · Drawdown: {prop_firm.drawdown_breaches} · Risk/trade: {prop_firm.risk_per_trade_breaches}
            <br />
            Breach rate: {prop_firm.breach_rate.toFixed(2)} per episode
          </div>
        </div>
      )}

      {/* Episode details toggle */}
      <div>
        <button
          type="button"
          className="mode-toggle"
          onClick={() => setShowEpisodes(!showEpisodes)}
          style={{
            padding: "0.375rem 0.75rem",
            fontSize: "0.6875rem",
            borderRadius: "0.375rem",
            cursor: "pointer",
          }}
        >
          {showEpisodes ? "Hide" : "Show"} Episode Details ({episodes.length})
        </button>

        {showEpisodes && episodes.length > 0 && (
          <div
            style={{
              marginTop: "0.5rem",
              overflowX: "auto",
              borderRadius: "0.5rem",
              border: "1px solid var(--line-subtle)",
            }}
          >
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: "0.6875rem",
                fontFamily: "monospace",
              }}
            >
              <thead>
                <tr style={{ background: "var(--bg-panel-muted)" }}>
                  <th style={thStyle}>#</th>
                  <th style={thStyle}>Trades</th>
                  <th style={thStyle}>Win Rate</th>
                  <th style={thStyle}>PF</th>
                  <th style={thStyle}>Expect</th>
                  <th style={thStyle}>PnL</th>
                  <th style={thStyle}>Signals</th>
                </tr>
              </thead>
              <tbody>
                {episodes.map((ep) => (
                  <tr key={ep.episode} style={{ borderTop: "1px solid var(--line-subtle)" }}>
                    <td style={tdStyle}>{ep.episode}</td>
                    <td style={tdStyle}>{ep.trades}</td>
                    <td style={{ ...tdStyle, color: ep.win_rate > 0.52 ? "var(--accent-positive)" : ep.win_rate < 0.48 ? "var(--accent-danger)" : "var(--text-body)" }}>
                      {(ep.win_rate * 100).toFixed(1)}%
                    </td>
                    <td style={{ ...tdStyle, color: ep.profit_factor > 1.0 ? "var(--accent-positive)" : "var(--accent-danger)" }}>
                      {ep.profit_factor === Infinity ? "∞" : ep.profit_factor.toFixed(2)}
                    </td>
                    <td style={{ ...tdStyle, color: ep.expectancy_r > 0 ? "var(--accent-positive)" : "var(--accent-danger)" }}>
                      {ep.expectancy_r.toFixed(3)}R
                    </td>
                    <td style={{ ...tdStyle, color: ep.net_pnl > 0 ? "var(--accent-positive)" : "var(--accent-danger)" }}>
                      {ep.net_pnl.toFixed(2)}
                    </td>
                    <td style={tdStyle}>{ep.signals}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  padding: "0.375rem 0.5rem",
  textAlign: "left",
  fontWeight: 600,
  color: "var(--text-muted)",
  whiteSpace: "nowrap",
};

const tdStyle: React.CSSProperties = {
  padding: "0.375rem 0.5rem",
  color: "var(--text-body)",
  whiteSpace: "nowrap",
};
