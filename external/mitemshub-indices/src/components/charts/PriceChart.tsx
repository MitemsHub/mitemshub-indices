"use client";

import React, { useEffect, useState, useCallback, useRef, useMemo } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";

type Tick = { epoch: number; price: number };

type ChartDataPoint = {
  time: string;
  V75: number | null;
  V100: number | null;
  epoch: number;
};

type SSEEvent =
  | { type: "initial"; symbol: string; ticks: Tick[]; timestamp: number }
  | { type: "tick"; symbol: string; tick: Tick; timestamp: number }
  | { type: "ready"; timestamp: number }
  | { type: "heartbeat"; timestamp: number }
  | { type: "error"; message: string };

function formatTime(epoch: number): string {
  const d = new Date(epoch * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatPrice(value: number | null): string {
  if (value === null) return "—";
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function mergeTicks(
  v75: Tick[],
  v100: Tick[],
  limit = 100,
): ChartDataPoint[] {
  const map = new Map<number, ChartDataPoint>();

  for (const t of v75) {
    const key = Math.round(t.epoch * 10); // 100ms precision for dedup
    const existing = map.get(key);
    if (existing) {
      existing.V75 = t.price;
    } else {
      map.set(key, { time: formatTime(t.epoch), V75: t.price, V100: null, epoch: t.epoch });
    }
  }

  for (const t of v100) {
    const key = Math.round(t.epoch * 10);
    const existing = map.get(key);
    if (existing) {
      existing.V100 = t.price;
    } else {
      map.set(key, { time: formatTime(t.epoch), V75: null, V100: t.price, epoch: t.epoch });
    }
  }

  const sorted = Array.from(map.values()).sort((a, b) => a.epoch - b.epoch);
  return sorted.slice(-limit);
}

/** Custom tooltip showing both V75 and V100 prices for a given timestamp. */
function CustomTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name?: string; value?: number | null; color?: string }>; label?: string }) {
  if (!active || !payload?.length) return null;

  return (
    <div
      className="rounded-xl border border-[var(--line-subtle)] px-3 py-2 text-xs shadow-lg"
      style={{ background: "var(--bg-panel-strong)" }}
    >
      <p className="mb-1 font-medium text-[var(--text-muted)]">{label}</p>
      {payload.map((entry) => (
        <p key={entry.name} style={{ color: entry.color }} className="font-mono">
          {entry.name}: {formatPrice(entry.value ?? null)}
        </p>
      ))}
    </div>
  );
}

/** Find the last non-null value for a given key in a data array. */
function findLastNonNull<T extends Record<string, unknown>>(arr: T[], key: keyof T): T[keyof T] | null {
  for (let i = arr.length - 1; i >= 0; i--) {
    if (arr[i][key] !== null) return arr[i][key];
  }
  return null;
}

/**
 * Custom hook for streaming tick data via SSE.
 * Falls back to polling if SSE connection fails,
 * then retries SSE with exponential backoff (30s → 60s → 120s → 300s).
 */
function useTickStream(limit = 100) {
  const [data, setData] = useState<ChartDataPoint[]>([]);
  const [lastUpdate, setLastUpdate] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [connectionLost, setConnectionLost] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<NodeJS.Timeout | null>(null);
  const fallbackIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptRef = useRef(0);
  const MAX_RECONNECT_ATTEMPTS = 10;

  // Store accumulated ticks per symbol for incremental updates
  const ticksRef = useRef<{ R_75: Tick[]; R_100: Tick[] }>({ R_75: [], R_100: [] });

  const updateData = useCallback(() => {
    const merged = mergeTicks(ticksRef.current.R_75, ticksRef.current.R_100, limit);
    setData(merged);
    setLastUpdate(new Date().toLocaleTimeString());
  }, [limit]);

  // Fallback polling function
  const pollTicks = useCallback(async () => {
    try {
      const res = await fetch("/api/ticks");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      ticksRef.current = json.ticks;
      updateData();
      setError(null);
    } catch {
      setError("Failed to load tick data");
    }
  }, [updateData]);

  // Schedule SSE reconnection with exponential backoff
  const scheduleReconnect = useCallback(() => {
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);

    // Stop retrying after MAX_RECONNECT_ATTEMPTS — show 'Connection Lost'
    if (reconnectAttemptRef.current >= MAX_RECONNECT_ATTEMPTS) {
      console.warn(`[SSE] Reached max reconnection attempts (${MAX_RECONNECT_ATTEMPTS}). Showing connection lost.`);
      setConnectionLost(true);
      return;
    }

    // Exponential backoff: 30s → 60s → 120s → 300s (max 5 minutes)
    const delays = [30_000, 60_000, 120_000, 300_000];
    const attempt = reconnectAttemptRef.current;
    const delay = delays[Math.min(attempt, delays.length - 1)];

    reconnectTimerRef.current = setTimeout(() => {
      reconnectAttemptRef.current += 1;
      console.log(`[SSE] Reconnecting (attempt ${reconnectAttemptRef.current}/${MAX_RECONNECT_ATTEMPTS})...`);
      setReconnecting(true);
      startSSE();
    }, delay);
  }, []); // scheduleReconnect references startSSE via closure

  // Start SSE connection
  const startSSE = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const es = new EventSource(`/api/ticks?stream=true&limit=${limit}`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const data: SSEEvent = JSON.parse(event.data);

        switch (data.type) {
          case "initial":
            // Replace ticks for this symbol with initial data
            ticksRef.current[data.symbol as keyof typeof ticksRef.current] = data.ticks;
            updateData();
            setError(null);
            break;

          case "tick":
            // Append new tick to the accumulator
            const symbolKey = data.symbol as keyof typeof ticksRef.current;
            const existingTicks = ticksRef.current[symbolKey];
            // Avoid duplicates by checking epoch
            if (existingTicks.length === 0 || existingTicks[existingTicks.length - 1].epoch < data.tick.epoch) {
              existingTicks.push(data.tick);
              // Keep only the last `limit` ticks
              if (existingTicks.length > limit * 2) {
                ticksRef.current[symbolKey] = existingTicks.slice(-limit);
              }
              updateData();
              setError(null);
            }
            break;

          case "ready":
            setIsStreaming(true);
            setConnectionLost(false);
            setReconnecting(false);
            setError(null);
            // Reset reconnect counter on successful connection
            reconnectAttemptRef.current = 0;
            // Stop polling fallback if it was running
            if (fallbackIntervalRef.current) {
              clearInterval(fallbackIntervalRef.current);
              fallbackIntervalRef.current = null;
            }
            break;

          case "heartbeat":
            // Connection is alive
            break;

          case "error":
            setError(data.message);
            break;
        }
      } catch {
        // Ignore parse errors
      }
    };

    es.onerror = () => {
      // SSE connection failed — fall back to polling
      setIsStreaming(false);
      es.close();
      eventSourceRef.current = null;

      // Start polling as fallback
      if (!fallbackIntervalRef.current) {
        void pollTicks();
        fallbackIntervalRef.current = setInterval(() => void pollTicks(), 3000);
      }

      // Schedule SSE reconnection with backoff
      scheduleReconnect();
    };
  }, [limit, updateData, pollTicks, scheduleReconnect]);

  // Manual reconnect handler — resets counter and retries immediately
  const reconnectNow = useCallback(() => {
    setConnectionLost(false);
    setReconnecting(true);
    reconnectAttemptRef.current = 0;
    if (fallbackIntervalRef.current) {
      clearInterval(fallbackIntervalRef.current);
      fallbackIntervalRef.current = null;
    }
    startSSE();
  }, [startSSE]);

  useEffect(() => {
    // Try SSE first
    startSSE();

    return () => {
      eventSourceRef.current?.close();
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (fallbackIntervalRef.current) clearInterval(fallbackIntervalRef.current);
    };
  }, [startSSE]);

  return { data, lastUpdate, error, isStreaming, connectionLost, reconnecting, reconnectNow };
}

export function PriceChart() {
  const { data, lastUpdate, error, isStreaming, connectionLost, reconnecting, reconnectNow } = useTickStream(100);
  const [collapsed, setCollapsed] = useState(false);
  const prevConnectionLostRef = useRef(false);

  // Auto-expand chart when SSE reconnects after being in Connection Lost state
  useEffect(() => {
    if (prevConnectionLostRef.current && !connectionLost && collapsed) {
      console.log("[PriceChart] SSE reconnected after Connection Lost — auto-expanding chart");
      setCollapsed(false);
    }
    prevConnectionLostRef.current = connectionLost;
  }, [connectionLost, collapsed]);

  // Compute price range for Y-axis domain (memoized to avoid re-computation on every render)
  const [yMin, yMax] = useMemo(() => {
    let minPrice = Infinity;
    let maxPrice = -Infinity;
    for (const d of data) {
      if (d.V75 !== null) {
        minPrice = Math.min(minPrice, d.V75);
        maxPrice = Math.max(maxPrice, d.V75);
      }
      if (d.V100 !== null) {
        minPrice = Math.min(minPrice, d.V100);
        maxPrice = Math.max(maxPrice, d.V100);
      }
    }
    const range = maxPrice - minPrice || 10;
    return [Math.floor(minPrice - range * 0.05), Math.ceil(maxPrice + range * 0.05)];
  }, [data]);

  // Latest prices for collapsed view — find last non-null value for each symbol
  const latestV75 = useMemo(() => findLastNonNull(data, "V75") as number | null, [data]);
  const latestV100 = useMemo(() => findLastNonNull(data, "V100") as number | null, [data]);

  // Previous prices for change calculation — iterate backwards from data.length - 3
  const prevV75 = useMemo(() => {
    for (let i = data.length - 3; i >= 0; i--) {
      if (data[i].V75 !== null) return data[i].V75;
    }
    return null;
  }, [data]);
  const prevV100 = useMemo(() => {
    for (let i = data.length - 3; i >= 0; i--) {
      if (data[i].V100 !== null) return data[i].V100;
    }
    return null;
  }, [data]);

  return (
    <div className="surface rounded-[1.5rem] mb-5">
      {/* Collapsible header */}
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        aria-expanded={!collapsed}
        aria-controls="price-chart-content"
        className="w-full flex items-center justify-between p-4 md:p-5 text-left transition-colors hover:bg-[var(--bg-surface-hover)] rounded-[1.5rem]"
      >
        <div className="flex items-center gap-3">
          {/* Chevron */}
          <svg
            className={`w-4 h-4 text-[var(--text-muted)] transition-transform duration-200 ${collapsed ? "" : "rotate-90"}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-strong)]">
              Live Price Feed
            </h3>
            <p className="text-xs text-[var(--text-muted)]">
              {collapsed ? (
                <>
                  V75: {formatPrice(latestV75)} · V100: {formatPrice(latestV100)}
                </>
              ) : (
                <>
                  Last {data.length} ticks · V75 & V100
                </>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {lastUpdate && (
            <span className="text-xs text-[var(--text-muted)]">
              {lastUpdate}
            </span>
          )}
          <span className={`status-badge ${connectionLost ? "status-badge--danger" : reconnecting ? "status-badge--warning" : isStreaming ? "status-badge--confirmed" : "status-badge--warning"}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${connectionLost ? "bg-[var(--accent-danger)]" : reconnecting ? "bg-[var(--accent-warn)]" : isStreaming ? "bg-[var(--accent-positive)]" : "bg-[var(--accent-warn)]"} ${!connectionLost ? "animate-pulse" : ""}`} />
            {connectionLost ? (
              <button type="button" onClick={reconnectNow} className="underline underline-offset-2 hover:text-[var(--accent-danger)] transition-colors">
                Connection Lost — Tap to Retry
              </button>
            ) : reconnecting ? "Reconnecting…" : isStreaming ? "Live" : "Polling"}
          </span>
        </div>
      </button>

      {/* Collapsible content with smooth transition */}
      <div
        id="price-chart-content"
        role="region"
        aria-hidden={collapsed}
        className="overflow-hidden transition-all duration-300 ease-in-out"
        style={{ maxHeight: collapsed ? 0 : '600px', opacity: collapsed ? 0 : 1 }}
      >
        <div className="px-4 pb-4 md:px-5 md:pb-5">
          {error ? (
            <div className="flex h-48 items-center justify-center text-sm text-[var(--accent-danger)]">
              {error}
            </div>
          ) : data.length === 0 ? (
            <div className="flex h-48 items-center justify-center">
              <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
                <div className="loading-pulse" />
                Waiting for tick data…
              </div>
            </div>
          ) : (
            <div className="h-56 md:h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="var(--line-subtle)"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="time"
                    tick={{ fontSize: 10, fill: "var(--text-muted)" }}
                    tickLine={false}
                    axisLine={{ stroke: "var(--line-subtle)" }}
                    interval="preserveStartEnd"
                    minTickGap={40}
                  />
                  <YAxis
                    domain={[yMin, yMax]}
                    tick={{ fontSize: 10, fill: "var(--text-muted)" }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v: number) =>
                      v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(Math.round(v))
                    }
                    width={45}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend
                    verticalAlign="top"
                    height={28}
                    wrapperStyle={{ fontSize: 11, paddingTop: 0 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="V75"
                    stroke="#1f4b99"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4, strokeWidth: 2 }}
                    animationDuration={300}
                  />
                  <Line
                    type="monotone"
                    dataKey="V100"
                    stroke="#0f6b57"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4, strokeWidth: 2 }}
                    animationDuration={300}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

      {/* Price summary cards */}
      {data.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-3">
          <PriceSummaryCard
            label="Volatility 75"
            current={latestV75}
            previous={prevV75}
          />
          <PriceSummaryCard
            label="Volatility 100"
            current={latestV100}
            previous={prevV100}
          />
        </div>
      )}
        </div>
      </div>
    </div>
  );
}

function PriceSummaryCard({
  label,
  current,
  previous,
}: {
  label: string;
  current: number | null;
  previous: number | null;
}) {
  const change =
    current !== null && previous !== null ? current - previous : null;
  const changePercent =
    change !== null && previous !== null && previous !== 0 ? (change / previous) * 100 : null;
  const isUp = change !== null && change > 0;

  return (
    <div
      className="rounded-xl border border-[var(--line-subtle)] px-3 py-2"
      style={{ background: "var(--bg-panel-muted)" }}
    >
      <p className="text-xs text-[var(--text-muted)]">{label}</p>
      <p className="font-mono text-lg font-semibold text-[var(--text-strong)]">
        {formatPrice(current)}
      </p>
      {change !== null && changePercent !== null && (
        <p
          className={`font-mono text-xs ${
            isUp ? "text-[var(--accent-positive)]" : change === 0 ? "text-[var(--text-muted)]" : "text-[var(--accent-danger)]"
          }`}
        >
          {isUp ? "▲" : change === 0 ? "—" : "▼"}{" "}
          {Math.abs(change).toFixed(2)} ({changePercent >= 0 ? "+" : ""}
          {changePercent.toFixed(3)}%)
        </p>
      )}
    </div>
  );
}
