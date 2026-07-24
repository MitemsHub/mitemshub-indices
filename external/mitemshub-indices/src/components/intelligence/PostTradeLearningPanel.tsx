"use client"

import type { PostTradeLearning } from "../../lib/contracts";

type PostTradeLearningPanelProps = {
  learning: PostTradeLearning | null;
};

export function PostTradeLearningPanel({ learning }: PostTradeLearningPanelProps) {
if (!learning) {
    return (
      <section className="intelligence-panel surface rounded-[1.5rem] p-4">
        <p className="utility-copy text-xs uppercase tracking-[0.2em]">Post-Trade Learning Summary</p>
        <p className="mt-4 text-base text-[var(--text-body)]">Complete trades to generate learning summary.</p>
      </section>
    );
  }

  return (
    <section className="intelligence-panel surface rounded-[1.5rem] p-4">
      <div className="flex items-center justify-between">
        <p className="utility-copy text-xs uppercase tracking-[0.2em]">Post-Trade Learning Summary</p>
        <span className="info-chip rounded-full px-2 py-1 text-xs text-blue-700 bg-blue-50">
          {learning.total_trades} Trades Analyzed
        </span>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard title="Win Rate" value={`${(learning.win_rate * 100).toFixed(1)}%`} />
        <StatCard title="Avg R Multiple" value={learning.avg_r_multiple > 0 ? `+${learning.avg_r_multiple.toFixed(2)}` : learning.avg_r_multiple.toFixed(2)} />
        <StatCard title="Profit Factor" value={learning.profit_factor === Infinity ? "∞" : learning.profit_factor.toFixed(2)} />
        <StatCard title="Avg Hold Time" value={`${Math.round(learning.avg_hold_time)} min`} />
      </div>

      <div className="mt-4 p-4 rounded-lg bg-gray-50 border border-gray-200">
        <p className="utility-copy text-xs uppercase tracking-[0.2em] text-gray-500 mb-3">Performance by Regime</p>
        <div className="space-y-2">
          {Object.entries(learning.regime_performance).map(([regime, stats]) => (
            <div key={regime} className="flex items-center justify-between p-3 rounded-lg bg-white border border-gray-200">
              <span className="font-medium text-gray-900">{regime.replace("_", " ")}</span>
              <div className="flex items-center gap-4 text-sm text-gray-600">
                <span>Trades: {stats.trades}</span>
                <span>Win Rate: {(stats.win_rate * 100).toFixed(1)}%</span>
                <span>Avg R: {stats.avg_r > 0 ? "+" : ""}{stats.avg_r.toFixed(2)}</span>
              </div>
            </div>
          ))}
          {Object.keys(learning.regime_performance).length === 0 && (
            <p className="text-sm text-gray-500 text-center py-4">No regime data available</p>
          )}
        </div>
      </div>

      {learning.recent_insights.length > 0 && (
        <div className="mt-4">
          <p className="utility-copy text-xs uppercase tracking-[0.2em] text-gray-500 mb-3">Recent Insights</p>
          <ul className="space-y-2">
            {learning.recent_insights.map((insight, i) => (
              <li key={i} className="flex items-start gap-2 p-3 rounded-lg bg-blue-50 border border-blue-200">
                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-blue-500 text-white text-xs flex items-center justify-center mt-0.5">💡</span>
                <span className="text-sm text-blue-800">{insight}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 p-4 rounded-lg bg-gray-50 border border-gray-200">
        <p className="utility-copy text-xs uppercase tracking-[0.2em] text-gray-500 mb-3">Calibration Quality</p>
        <div className="flex items-center gap-4">
          <div className="flex-1">
            <p className="utility-copy text-xs uppercase tracking-[0.1em] text-gray-500">Calibration Score</p>
            <p className="text-lg font-bold text-blue-600">{(learning.calibration_quality * 100).toFixed(0)}%</p>
          </div>
          <div className="flex-1">
            <p className="utility-copy text-xs uppercase tracking-[0.1em] text-gray-500">Model Version</p>
            <p className="text-lg font-bold text-gray-900">{learning.model_version}</p>
          </div>
        </div>
      </div>
    </section>
  );
}

function StatCard({ title, value }: { title: string; value: string }) {
  return (
    <div className="info-card rounded-[1rem] p-4 text-center">
      <p className="utility-copy text-xs uppercase tracking-[0.2em] text-gray-500">{title}</p>
      <p className="mt-2 text-lg font-bold text-gray-900">{value}</p>
    </div>
  );
}