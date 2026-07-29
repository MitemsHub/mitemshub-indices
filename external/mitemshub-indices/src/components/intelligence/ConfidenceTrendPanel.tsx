"use client"

import type { ConfidenceTrend } from "../../lib/contracts";
import { DataFreshnessDot } from "./DataFreshnessDot";
import { ConfidenceTrendSkeleton } from "./ConfidenceTrendSkeleton";

type ConfidenceTrendPanelProps = {
  trend: ConfidenceTrend | null;
  loading?: boolean;
};

export function ConfidenceTrendPanel({ trend, loading }: ConfidenceTrendPanelProps) {
  if (loading) {
    return <ConfidenceTrendSkeleton />;
  }

  if (!trend || !trend.history.length) {
    return (
      <div className="intelligence-panel surface rounded-[1.5rem] p-4">
        <div className="flex items-center gap-2">
          <DataFreshnessDot live={false} />
          <p className="utility-copy text-xs uppercase tracking-[0.2em]">Confidence Trend</p>
        </div>
        <p className="mt-4 text-base text-[var(--text-body)]">Run live reads to build confidence history.</p>
      </div>
    );
  }

  const trendColors = {
    improving: "text-green-700 bg-green-50 border-green-200",
    stable: "text-blue-700 bg-blue-50 border-blue-200",
    degrading: "text-red-700 bg-red-50 border-red-200",
  };

  return (
    <div className="intelligence-panel surface rounded-[1.5rem] p-4">        <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <DataFreshnessDot live={true} />
          <p className="utility-copy text-xs uppercase tracking-[0.2em]">Confidence Trend</p>
        </div>
        <span className={`info-chip rounded-full px-3 py-1 text-sm font-medium ${trendColors[trend.trend] || trendColors.stable}`}>
          Trend: {trend.trend.charAt(0).toUpperCase() + trend.trend.slice(1)}
        </span>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <DetailCard
          title="Current"
          value={trend.history[0] ? `${(trend.history[0].confidence * 100).toFixed(1)}%` : "—"}
          hint="Latest confidence"
        />
        <DetailCard
          title="5-Read Avg"
          value={trend.history.length >= 5
            ? `${(trend.history.slice(0, 5).reduce((a, b) => a + b.confidence, 0) / 5 * 100).toFixed(1)}%`
            : "—"}
          hint="Average over last 5 reads"
        />
        <DetailCard
          title="Volatility"
          value={`${(trend.volatility * 100).toFixed(1)}%`}
          hint="Confidence volatility"
        />
      </div>

      <div className="mt-4">
        <p className="utility-copy text-xs uppercase tracking-[0.2em] text-gray-500 mb-3">Confidence History</p>
        <div className="h-64 relative">
          <svg className="w-full h-full" viewBox="0 0 800 256" preserveAspectRatio="none">
            <defs>
              <linearGradient id="confidenceGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%" stopColor="rgba(59, 130, 246, 0.3)" />
                <stop offset="100%" stopColor="rgba(59, 130, 246, 0)" />
              </linearGradient>
            </defs>
            <path
              d={generatePath(trend.history)}
              fill="url(#confidenceGradient)"
              stroke="#3b82f6"
              strokeWidth="2"
              fillOpacity="0.3"
            />
            <path
              d={generatePath(trend.history)}
              fill="none"
              stroke="#3b82f6"
              strokeWidth="2"
            />
            {trend.history.map((point, i) => {
              const x = i / Math.max(trend.history.length - 1, 1) * 760 + 20;
              const y = 236 - point.confidence * 216;
              const rotation = `rotate(-45 ${x} ${y + 22})`;
              return (
                <g key={i}>
                  <circle
                    cx={x}
                    cy={y}
                    r={4}
                    fill="#3b82f6"
                    stroke="white"
                    strokeWidth={2}
                  />
                  <text x={x} y={y + 22} textAnchor="middle" fontSize="8" fill="gray" transform={rotation}>
                    {new Date(point.timestamp).toLocaleDateString()}
                  </text>
                </g>
              );
            })}
          </svg>

          <div className="absolute bottom-0 left-0 right-0 flex justify-between text-xs text-gray-500 px-2">
            {trend.history.length > 1 && [
              trend.history[trend.history.length - 1].timestamp,
              trend.history[Math.floor(trend.history.length / 2)].timestamp,
              trend.history[0].timestamp,
            ].map((ts, i) => (
              <span key={i}>{new Date(ts).toLocaleDateString()}</span>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4">
        <p className="utility-copy text-xs uppercase tracking-[0.2em] text-gray-500 mb-3">Recent Readings</p>
        <div className="space-y-2 max-h-48 overflow-y-auto">
          {trend.history.slice(0, 10).map((point, i) => (
            <ConfidenceHistoryRow key={i} point={point} index={i} />
          ))}
        </div>
      </div>
    </div>
  );
}

function ConfidenceHistoryRow({ point, index }: { point: any; index: number }) {

  return (
    <div className="flex items-center justify-between p-3 rounded-lg bg-gray-50 border border-gray-100">
      <div className="flex items-center gap-3">
        <span className="text-sm font-mono text-gray-500 w-8">{index + 1}</span>
        <div>
          <p className="text-sm font-medium text-gray-900">
            {new Date(point.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </p>
          <p className="text-xs text-gray-500">{point.regime} • {point.direction_bias}</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <div className="w-20 h-2 bg-gray-100 rounded-full overflow-hidden">
          <div className="h-full bg-blue-500 rounded-full" style={{ width: `${point.confidence * 100}%` }} />
        </div>
        <span className="text-sm font-semibold text-gray-900 w-16 text-right">
          {(point.confidence * 100).toFixed(1)}%
        </span>
        {point.outcome && (
          <span className={`info-chip rounded-full px-2 py-0.5 text-xs ${["win", "loss", "pending", "cancelled"].includes(point.outcome) ? ["text-green-700 bg-green-50", "text-red-700 bg-red-50", "text-blue-700 bg-blue-50", "text-gray-700 bg-gray-50"][["win", "loss", "pending", "cancelled"].indexOf(point.outcome)] : "text-gray-700 bg-gray-50"}`}>
            {point.outcome}
          </span>
        )}
      </div>
    </div>
  );
}

function generatePath(history: any[]): string {
  if (history.length < 2) return "M 20 236 L 20 236";

  const width = 760;
  const stepX = width / Math.max(history.length - 1, 1);

  let path = `M 20 ${236 - history[0].confidence * 216}`;

  for (let i = 1; i < history.length; i++) {
    const x = 20 + i * stepX;
    const y = 236 - history[i].confidence * 216;
    path += ` L ${x} ${y}`;
  }

  // Add area to bottom
  path += ` L ${20 + (history.length - 1) * stepX} 252 L 20 252 Z`;

  return path;
}

function DetailCard({
  title,
  value,
  hint,
}: {
  title: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="info-card rounded-[1rem] p-4">
      <p className="utility-copy text-xs uppercase tracking-[0.2em] text-gray-500">{title}</p>
      <p className="mt-2 text-base font-semibold text-gray-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}