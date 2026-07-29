"use client"

import type { SystemPerformance } from "../../lib/contracts"

type Props = {
  performance: SystemPerformance | null
  loading?: boolean
}

function MetricCard({ label, value, subtitle, color }: { label: string; value: string; subtitle?: string; color?: string }) {
  return (
    <div className="p-3 md:p-4 rounded-xl bg-[var(--bg-panel-muted)] border border-[var(--line-subtle)]">
      <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-[var(--text-muted)] mb-1">{label}</p>
      <p className={`text-lg md:text-xl font-bold ${color || "text-[var(--text-strong)]"}`}>{value}</p>
      {subtitle && <p className="text-[10px] md:text-xs text-[var(--text-muted)] mt-0.5">{subtitle}</p>}
    </div>
  )
}

function ScoreBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="w-full h-2 bg-[var(--line-subtle)] rounded-full overflow-hidden">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

export function SystemPerformancePanel({ performance, loading }: Props) {
  if (loading) {
    return (
      <section className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
        <div className="flex items-center gap-2 mb-4">
          <div className="loading-pulse" />
          <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">System Performance</p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="h-20 rounded-xl bg-[var(--bg-panel-muted)] animate-pulse" />
          ))}
        </div>
      </section>
    )
  }

  if (!performance || performance.total_trades === 0) {
    return (
      <section className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
        <div className="flex items-center gap-2 mb-3">
          <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">System Performance</p>
        </div>
        <p className="text-sm text-[var(--text-body)]">No completed trades yet. Performance metrics will appear once trades are closed and outcomes recorded.</p>
      </section>
    )
  }

  const p = performance
  const winRateColor = p.win_rate >= 0.55 ? "text-[var(--accent-positive)]" : p.win_rate >= 0.45 ? "text-[var(--text-strong)]" : "text-[var(--accent-danger)]"
  const pfColor = p.profit_factor >= 1.5 ? "text-[var(--accent-positive)]" : p.profit_factor >= 1.0 ? "text-[var(--text-strong)]" : "text-[var(--accent-danger)]"
  const rColor = p.avg_r_multiple >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-danger)]"
  const ddColor = p.max_drawdown_pct <= 5 ? "text-[var(--accent-positive)]" : p.max_drawdown_pct <= 10 ? "text-[var(--accent-warn)]" : "text-[var(--accent-danger)]"

  return (
    <section className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
      <div className="flex items-center justify-between mb-4">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">System Performance</p>
        <span className="text-[10px] text-[var(--text-muted)]">{p.time_span}</span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <MetricCard
          label="Total Trades"
          value={String(p.total_trades)}
          subtitle={`${p.wins}W / ${p.losses}L`}
        />
        <MetricCard
          label="Win Rate"
          value={`${(p.win_rate * 100).toFixed(1)}%`}
          color={winRateColor}
          subtitle="target: ≥55%"
        />
        <MetricCard
          label="Profit Factor"
          value={p.profit_factor >= 999 ? "∞" : p.profit_factor.toFixed(2)}
          color={pfColor}
          subtitle="gross profit / gross loss"
        />
        <MetricCard
          label="Avg R-Multiple"
          value={`${p.avg_r_multiple >= 0 ? "+" : ""}${p.avg_r_multiple.toFixed(2)}R`}
          color={rColor}
          subtitle="average return per trade"
        />
        <MetricCard
          label="Max Drawdown"
          value={`${p.max_drawdown_pct.toFixed(1)}%`}
          color={ddColor}
          subtitle={`$${Math.abs(p.max_drawdown_amount).toFixed(0)} from peak`}
        />
        <MetricCard
          label="Net P&L"
          value={`${p.net_pnl >= 0 ? "+" : ""}$${p.net_pnl.toFixed(0)}`}
          color={p.net_pnl >= 0 ? "text-[var(--accent-positive)]" : "text-[var(--accent-danger)]"}
          subtitle="realized profit/loss"
        />
      </div>

      {/* Win rate bar */}
      <div className="mt-4">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] text-[var(--text-muted)]">Win Rate</span>
          <span className="text-[10px] font-mono text-[var(--text-body)]">{(p.win_rate * 100).toFixed(1)}%</span>
        </div>
        <ScoreBar value={p.win_rate} max={1} color="bg-[var(--accent-positive)]" />
      </div>

      {/* Profit factor bar */}
      <div className="mt-3">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] text-[var(--text-muted)]">Profit Factor</span>
          <span className="text-[10px] font-mono text-[var(--text-body)]">{p.profit_factor >= 999 ? "∞" : p.profit_factor.toFixed(2)}</span>
        </div>
        <ScoreBar value={p.profit_factor} max={3} color="bg-[var(--accent-ink)]" />
      </div>

      {/* Drawdown bar */}
      <div className="mt-3">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] text-[var(--text-muted)]">Max Drawdown</span>
          <span className="text-[10px] font-mono text-[var(--text-body)]">{p.max_drawdown_pct.toFixed(1)}%</span>
        </div>
        <ScoreBar value={p.max_drawdown_pct} max={20} color="bg-[var(--accent-danger)]" />
      </div>
    </section>
  )
}
