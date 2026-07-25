"use client"

import type { FreshCallResponse } from "../../lib/contracts";
import { formatPrice } from "../../lib/formatters";

type DecisionHistoryPanelProps = {
  history: FreshCallResponse[] | null;
  limit?: number;
};

export function DecisionHistoryPanel({ history, limit = 15 }: DecisionHistoryPanelProps) {
  const items = history || [];

  if (!items.length) {
    return (
      <div className="intelligence-panel surface rounded-[1.5rem] p-4">
        <p className="utility-copy text-xs uppercase tracking-[0.2em]">Decision History</p>
        <p className="mt-4 text-base text-[var(--text-body)]">No decision history available.</p>
      </div>
    );
  }

  const displayed = items.slice(0, limit);

  return (
    <section className="intelligence-panel surface rounded-[1.5rem] p-4">
      <div className="flex items-center justify-between">
        <p className="utility-copy text-xs uppercase tracking-[0.2em]">Decision History</p>
        <span className="info-chip rounded-full px-2 py-1 text-xs">{displayed.length} entries</span>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)]">
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Time</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Symbol</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Call</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Confidence</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Regime</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Bias</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Status</th>
              <th className="text-left py-2 px-3 utility-copy text-xs uppercase tracking-[0.1em]">Price</th>
            </tr>
          </thead>
          <tbody>
            {displayed.map((entry, index) => (
              <tr key={index} className="border-b border-[var(--border)]/50 hover:bg-gray-50/50">
                <td className="py-2 px-3 text-sm text-gray-500">
                  {new Date(entry.generated_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                </td>
                <td className="py-2 px-3 text-sm font-mono font-medium text-gray-900">{entry.symbol}</td>
                <td className="py-2 px-3">
                  <span className={`info-chip rounded-full px-2 py-0.5 text-xs ${entry.call === "buy_candidate" ? "text-green-700 bg-green-50" : entry.call === "sell_candidate" ? "text-red-700 bg-red-50" : "text-gray-600 bg-gray-50"}`}>
                    {entry.call.replace("_", " ").toUpperCase()}
                  </span>
                </td>
                <td className="py-2 px-3">
                  {entry.confidence !== null && entry.confidence !== undefined ? (
                    <>
                      <div className="w-20 h-2 bg-gray-100 rounded-full overflow-hidden inline-block">
                        <div className="h-full bg-blue-500" style={{ width: `${(entry.confidence || 0) * 100}%` }} />
                      </div>
                      <span className="ml-2 text-sm font-mono font-semibold text-gray-900">
                        {(entry.confidence * 100).toFixed(1)}%
                      </span>
                    </>
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                </td>
                <td className="py-2 px-3 text-sm text-gray-500">{entry.regime || "—"}</td>
                <td className="py-2 px-3 text-sm text-gray-500">{entry.direction_bias || "—"}</td>
                <td className="py-2 px-3">
                  <span className={`info-chip rounded-full px-2 py-0.5 text-xs ${entry.trade_status === "valid" ? "text-green-700 bg-green-50" : entry.trade_status === "invalid" ? "text-red-700 bg-red-50" : "text-gray-600 bg-gray-50"}`}>
                    {entry.trade_status}
                  </span>
                </td>
                <td className="py-2 px-3 text-sm font-mono font-medium text-right">
                  {entry.current_close !== null && entry.current_close !== undefined ? (
                    formatPrice(entry.current_close)
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {items.length > limit && (
        <div className="mt-4 text-center">
          <p className="text-sm text-gray-500">Showing {limit} of {items.length} entries</p>
        </div>
      )}
    </section>
  );
}