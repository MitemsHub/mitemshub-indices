/**
 * Shared SSE connection state.
 *
 * Module-scoped variables are per-process in Node.js, so any route handler
 * in the same server process can read/write these. This lets the /api/ticks
 * SSE endpoint update metrics that /api/system/sse-status can expose.
 */

export const MAX_SSE_CONNECTIONS = 5;

let activeSseConnections = 0;

export function getActiveSseConnections(): number {
  return activeSseConnections;
}

export function incrementSseConnections(): number {
  activeSseConnections += 1;
  return activeSseConnections;
}

export function decrementSseConnections(): number {
  activeSseConnections = Math.max(0, activeSseConnections - 1);
  return activeSseConnections;
}

// ── Connection state history ──────────────────────────────────
// Tracks the last N SSE state transitions for the diagnostics panel.
export type SseStateTransition = {
  state: "connected" | "disconnected" | "error";
  timestamp: number;
  message?: string;
};

const MAX_HISTORY = 20;
const stateHistory: SseStateTransition[] = [];

export function recordSseStateChange(transition: SseStateTransition): void {
  stateHistory.push(transition);
  if (stateHistory.length > MAX_HISTORY) {
    stateHistory.shift();
  }
}

export function getStateHistory(): SseStateTransition[] {
  return [...stateHistory];
}

// ── Byte-offset cache stats ───────────────────────────────────
// Exposed so the diagnostics endpoint can report cache hit rates.
let cacheHits = 0;
let cacheMisses = 0;

export function recordCacheHit(): void {
  cacheHits += 1;
}

export function recordCacheMiss(): void {
  cacheMisses += 1;
}

export function getCacheStats(): { hits: number; misses: number; hitRatio: number } {
  const total = cacheHits + cacheMisses;
  return {
    hits: cacheHits,
    misses: cacheMisses,
    hitRatio: total > 0 ? cacheHits / total : 0,
  };
}

export function resetCacheStats(): void {
  cacheHits = 0;
  cacheMisses = 0;
}

// ── Full status snapshot ──────────────────────────────────────
/**
 * Compute rolling connection uptime percentage over the last N minutes.
 *
 * Walks the state history backward from now, tracking how much time was
 * spent in the "connected" state. If the oldest entry in the window is
 * a "connected" event (i.e., the connection was live before the window
 * started), we assume it was connected for the entire pre-window period.
 *
 * Returns a number between 0 and 100.
 */
export function getRollingUptime(minutes: number = 5): number {
  const now = Date.now();
  const windowStart = now - minutes * 60_000;
  const history = getStateHistory();

  if (history.length === 0) return 0;

  // Walk backward through history, accumulating connected time
  let connectedMs = 0;
  let lastTimestamp = now;

  for (let i = history.length - 1; i >= 0; i--) {
    const entry = history[i];
    const entryTime = Math.max(entry.timestamp, windowStart);
    const duration = lastTimestamp - entryTime;

    if (duration > 0 && entry.state === "connected") {
      connectedMs += duration;
    }

    lastTimestamp = entryTime;
    if (entry.timestamp <= windowStart) break;
  }

  // If the oldest entry in the window is "connected", the connection
  // was live before the window started — count the remaining time
  if (lastTimestamp > windowStart && history.length > 0) {
    const oldest = history[0];
    if (oldest.state === "connected") {
      connectedMs += lastTimestamp - windowStart;
    }
  }

  const totalMs = now - windowStart;
  return totalMs > 0 ? Math.min(100, Math.round((connectedMs / totalMs) * 100)) : 0;
}

export type SseStatusSnapshot = {
  activeConnections: number;
  maxConnections: number;
  stateHistory: SseStateTransition[];
  cacheStats: { hits: number; misses: number; hitRatio: number };
  uptime: number; // ms since server started
  rollingUptime: number; // 0-100, percentage over last 5 minutes
};

const serverStartTime = Date.now();

export function getSseStatus(): SseStatusSnapshot {
  return {
    activeConnections: getActiveSseConnections(),
    maxConnections: MAX_SSE_CONNECTIONS,
    stateHistory: getStateHistory(),
    cacheStats: getCacheStats(),
    uptime: Date.now() - serverStartTime,
    rollingUptime: getRollingUptime(5),
  };
}
