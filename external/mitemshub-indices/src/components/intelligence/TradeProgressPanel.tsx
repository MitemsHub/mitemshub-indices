"use client"

import type { TradeProgress } from "../../lib/contracts";
import { formatPrice } from "../../lib/formatters";

type TradeProgressPanelProps = {
  progress: TradeProgress | null;
  currentPrice?: number | null;
};

type TradeProgressEvent = {
  timestamp: string;
  type: string;
  description: string;
  price: number | null;
  guardian_state: string | null;
  confidence: number | null;
};

export function TradeProgressPanel({ progress, currentPrice }: TradeProgressPanelProps) {
  if (!progress || !progress.events.length) {
    return (
      <section className="intelligence-panel surface rounded-[1.5rem] p-4">
        <p className="utility-copy text-xs uppercase tracking-[0.2em]">Trade Progress Timeline</p>
        <p className="mt-4 text-base text-[var(--text-body)]">No trade events yet. Run a live read to start tracking.</p>
      </section>
    );
  }

  return (
    <section className="intelligence-panel surface rounded-[1.5rem] p-4">
      <div className="flex items-center justify-between">
        <p className="utility-copy text-xs uppercase tracking-[0.2em]">Trade Progress Timeline</p>
        <div className="flex items-center gap-2">
          <span className="info-chip rounded-full px-2 py-1 text-xs">
            Phase: {progress.current_phase}
          </span>
          {progress.time_in_phase !== null && (
            <span className="info-chip rounded-full px-2 py-1 text-xs text-gray-600 bg-gray-50">
              {progress.time_in_phase}s in phase
            </span>
          )}
        </div>
      </div>

      <div className="mt-4">
        <div className="relative">
          <div className="absolute left-4 top-0 bottom-0 w-px bg-gray-200" />
          <div className="space-y-4 ml-4">
            {progress.events.map((event, index) => (
              <TimelineEvent key={index} event={event} isLast={index === progress.events.length - 1} />
            ))}
          </div>
        </div>
      </div>

      {currentPrice !== null && currentPrice !== undefined && (
        <div className="mt-4 p-4 rounded-lg bg-gray-50 border border-gray-200">
          <p className="utility-copy text-xs uppercase tracking-[0.2em] text-gray-500 mb-2">Current Price Context</p>
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <p className="utility-copy text-xs uppercase tracking-[0.1em] text-gray-500">Current Price</p>
              <p className="text-lg font-bold text-gray-900">{formatPrice(currentPrice)}</p>
            </div>
            <div className="flex-1">
              <p className="utility-copy text-xs uppercase tracking-[0.1em] text-gray-500">Last Event</p>
              <p className="text-base font-medium text-gray-700">
                {progress.events[progress.events.length - 1]?.description || "—"}
              </p>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function TimelineEvent({
  event,
  isLast,
}: {
  event: TradeProgressEvent;
  isLast: boolean;
}) {
  const typeColors: Record<string, { bg: string; text: string; border: string; icon: string }> = {
    call_generated: { bg: "bg-blue-50", text: "text-blue-700", border: "border-blue-200", icon: "●" },
    guardian_update: { bg: "bg-purple-50", text: "text-purple-700", border: "border-purple-200", icon: "◆" },
    confirmation: { bg: "bg-green-50", text: "text-green-700", border: "border-green-200", icon: "✓" },
    execution_armed: { bg: "bg-amber-50", text: "text-amber-700", border: "border-amber-200", icon: "▲" },
    entry_filled: { bg: "bg-green-100", text: "text-green-800", border: "border-green-300", icon: "✓" },
    stop_hit: { bg: "bg-red-50", text: "text-red-700", border: "border-red-200", icon: "✗" },
    target_hit: { bg: "bg-green-100", text: "text-green-800", border: "border-green-300", icon: "★" },
    invalidation: { bg: "bg-red-50", text: "text-red-700", border: "border-red-200", icon: "✕" },
    plan_invalidated: { bg: "bg-red-50", text: "text-red-700", border: "border-red-200", icon: "✕" },
  };

  const colors = typeColors[event.type] || { bg: "bg-gray-50", text: "text-gray-700", border: "border-gray-200", icon: "●" };

  return (
    <div className="relative flex gap-3">
      <div className="flex flex-col items-center flex-shrink-0">
        <div className={`w-3 h-3 rounded-full border-2 ${colors.border} ${colors.text} flex items-center justify-center`}>
          <span className="text-[10px] font-bold">{colors.icon}</span>
        </div>
        {!isLast && <div className="w-px h-full bg-gray-200 mt-1" />}
      </div>
      <div className="flex-1 min-w-0">
        <div className={`flex items-start gap-3 p-3 rounded-lg border ${colors.bg} ${colors.border}`}>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-gray-900">{event.description}</span>
              <span className={`info-chip rounded-full px-2 py-0.5 text-xs ${event.type === "entry_filled" || event.type === "target_hit" ? "text-green-700 bg-green-50" : event.type === "stop_hit" || event.type === "invalidation" || event.type === "plan_invalidated" ? "text-red-700 bg-red-50" : "text-gray-600 bg-gray-50"}`}>
                {event.type.replace("_", " ")}
              </span>
            </div>
            <p className="mt-1 text-sm text-gray-600">{event.type === "guardian_update" ? event.description : `${event.description} at ${event.price ? formatPrice(event.price) : "—"}`}</p>
            <div className="mt-2 flex items-center gap-3 text-xs text-gray-500">
              <span>{new Date(event.timestamp).toLocaleTimeString()}</span>
              {event.confidence !== null && event.confidence !== undefined && (
                <span>Confidence: {(event.confidence * 100).toFixed(0)}%</span>
              )}
              {event.guardian_state && (
                <span className="info-chip rounded-full px-2 py-0.5 text-xs text-purple-700 bg-purple-50">
                  Guardian: {event.guardian_state}
                </span>
              )}
            </div>
          </div>
          {event.price !== null && event.price !== undefined && (
            <div className="w-24 text-right">
              <p className="text-sm font-mono font-semibold text-gray-900">{formatPrice(event.price)}</p>
              {event.confidence !== null && event.confidence !== undefined && (
                <p className="text-xs text-gray-500">Conf: {(event.confidence * 100).toFixed(0)}%</p>
              )}
            </div>
          )}
        </div>
      </div>
      {!isLast && <div className="w-px h-full bg-gray-200 ml-3.5" />}
    </div>
  );
}

