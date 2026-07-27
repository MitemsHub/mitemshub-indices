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
export type SseStatusSnapshot = {
  activeConnections: number;
  maxConnections: number;
  stateHistory: SseStateTransition[];
  cacheStats: { hits: number; misses: number; hitRatio: number };
  uptime: number; // ms since server started
};

const serverStartTime = Date.now();

export function getSseStatus(): SseStatusSnapshot {
  return {
    activeConnections: getActiveSseConnections(),
    maxConnections: MAX_SSE_CONNECTIONS,
    stateHistory: getStateHistory(),
    cacheStats: getCacheStats(),
    uptime: Date.now() - serverStartTime,
  };
}
