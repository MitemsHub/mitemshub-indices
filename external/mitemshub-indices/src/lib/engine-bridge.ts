import { appendFile, mkdir, open, readFile, stat, writeFile } from "node:fs/promises";
import { existsSync, readFileSync } from "node:fs";

import { dirname, join } from "node:path";
import {
  withImportCheck,
  execFileAsync,
  getPipelineDiagnostics,
  recordPipelineError,
  recordPipelineGuardianReason,
  recordPipelineRetry,
  recordPipelineStaleDataSince,
  recordPipelineStderr,
  runPythonScript,
  __testResetImportCache,
  __testRunPythonScript,
  createTtlCache,
} from "./python-runner";
import {
  freshCallResponseSchema,
  guardianStatusSchema,
  type AccountMode,
  type FreshCallResponse,
  type GuardianStatus,
  type PropConnectionInput,
  type PropProfileResponse,
  type PropProfileRequest,
  type TradingMode,
} from "./contracts";
// Mock data removed — the system uses only real data from Deriv.
// When the live bridge is unavailable, the UI shows "unavailable" state.
import {
  submitOrderResponseSchema,
  closePositionResponseSchema,
  type ExecutionMode,
  type SubmitOrderResponse,
} from "./contracts";
import { evaluatePropCompliance, type PropAccountState } from "./prop-policy";

// Re-export the python-runner test helpers and diagnostics for existing callers.
export {
  __testRunPythonScript,
  __testResetImportCache,
  getPipelineDiagnostics,
} from "./python-runner";

type SymbolCode = FreshCallResponse["symbol"];
type BaseFreshCall = Omit<
  FreshCallResponse,
  | "account_mode"
  | "prop_compliance"
  | "prop_adjusted_risk"
  | "prop_block_reason"
  | "prop_remaining_daily_buffer"
  | "prop_remaining_overall_buffer"
  | "trading_mode"
> & { trading_mode?: TradingMode | null };
type LivePropProfileConfig = {
  server: string;
  login: string;
  password: string;
  terminalPath: string | null;
  startingBalance: number;
  highImpactNewsLockout: boolean;
  profile: PropAccountState["profile"];
};
type Mt5TestFileRecord = {
  success: boolean;
  error: string | null;
  server: string | null;
  terminal_path: string | null;
  duration_ms: number;
  account_name: string | null;
  account_balance: number | null;
  tested_at: string;
};

type LiveSnapshotMode = "manual" | "prepared";
type LiveSnapshotWarmupProfile = {
  warmupCount?: number;
};
type PreparedCallReusePolicy = "eligible_only" | "never";
type LiveSnapshotReadOptions = {
  engineRoot: string;
  symbol: SymbolCode;
  mode?: LiveSnapshotMode;
  warmupProfile?: LiveSnapshotWarmupProfile;
  tradingMode?: TradingMode;
  skipApi?: boolean;
  signal?: AbortSignal;
};

const DEFAULT_HISTORY_LIMIT = 6;

function resolveTerminalPath(): string | null {
  const explicit = process.env.SYNTHETIC_MT5_TERMINAL_PATH?.trim();
  if (explicit) {
    if (existsSync(explicit)) return explicit;
    console.warn(`[engine-bridge] SYNTHETIC_MT5_TERMINAL_PATH set but file not found: ${explicit}`);
    return explicit;
  }
  return null;
}

const DEFAULT_PROP_STARTING_BALANCE = 5000;
const LIVE_SNAPSHOT_MAX_ATTEMPTS = 2;
const LIVE_SNAPSHOT_TIMEOUT_MS = 35000;
const DEFAULT_MANUAL_SNAPSHOT_MAX_LIVE_TICKS = 12;
const DEFAULT_PREPARED_SNAPSHOT_MAX_LIVE_TICKS = 40;
const DEFAULT_COLD_SNAPSHOT_WARMUP_COUNT = 3000;
const DEFAULT_PREPARED_SNAPSHOT_WARMUP_COUNT = 1000; // Higher warmup = better CSV history for fallback
const PREPARED_CALL_ACTIONABLE_MAX_AGE_MS = 60 * 1000;
const PREPARED_CALL_TRANSIENT_MAX_AGE_MS = 30 * 1000;
const PREPARED_CALL_NEAR_THRESHOLD_RECHECK_CONFIDENCE = 0.48;
const DEFAULT_PREPARED_CALL_WARMUP_REFRESH_MS = 45 * 1000;
const DEFAULT_WARMUP_TICK_SAMPLE_COUNT = 4;
const PREPARED_CALL_WARMUP_SYMBOLS: SymbolCode[] = ["R_75", "R_100"];
const PREPARED_CALL_WARMUP_MODES: TradingMode[] = ["sniper", "active_trader"];

// ── Bridge state persistence (survives hot reloads) ────────────
// Persists the warmup cache to `{engineRoot}/data/bridge_state.json` so that
// server restarts (e.g., Next.js hot reloads) don't re-run all 4 warmup calls
// unnecessarily. The file is loaded synchronously on module init and saved
// asynchronously after each warmup cycle completes.

type BridgeState = {
  warmupCsvTimestamps: Record<string, { csvMtime: number; cachedAt: number }>;
  lastWarmupAt: string | null;
  warmupCycleCounter: number;
  warmupCacheHits: Record<string, number>;
  warmupCacheMisses: Record<string, number>;
  engineVersionCache: string | null | undefined;
  csvByteCache: Record<string, { byteOffset: number; tickCount: number; mtime: number }>;
  csvStaticMtimes: Record<string, { mtime: number; seenAt: number }>;
  mt5ProcessLastResult: boolean | null;
};

function getBridgeStatePath(engineRoot: string): string {
  return join(engineRoot, "data", "bridge_state.json");
}

function loadBridgeState(): void {
  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) return;
  const path = getBridgeStatePath(engineRoot);
  if (!existsSync(path)) return;
  try {
    const raw = readFileSync(path, "utf8");
    const state = JSON.parse(raw) as BridgeState;
    for (const [key, entry] of Object.entries(state.warmupCsvTimestamps)) {
      warmupCsvTimestamps.setWithTimestamp(key, { csvMtime: entry.csvMtime }, entry.cachedAt);
    }
    if (state.lastWarmupAt !== undefined) lastWarmupAt = state.lastWarmupAt;
    if (state.warmupCycleCounter !== undefined) warmupCycleCounter = state.warmupCycleCounter;
    if (state.warmupCacheHits !== undefined) {
      warmupCacheHits = { ...warmupCacheHits, ...state.warmupCacheHits };
    }
    if (state.warmupCacheMisses !== undefined) {
      warmupCacheMisses = { ...warmupCacheMisses, ...state.warmupCacheMisses };
    }
    if (state.engineVersionCache !== undefined) engineVersionCache = state.engineVersionCache;
    for (const [key, entry] of Object.entries(state.csvByteCache ?? {})) {
      csvByteCache.set(key, entry);
    }
    for (const [key, entry] of Object.entries(state.csvStaticMtimes ?? {})) {
      csvStaticMtimes.set(key, entry);
    }
    if (state.mt5ProcessLastResult !== undefined) {
      mt5ProcessLastResult = state.mt5ProcessLastResult;
    }
  } catch {
    // Corrupted file — start fresh
  }
}

async function saveBridgeState(): Promise<void> {
  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) return;
  const path = getBridgeStatePath(engineRoot);
  const state: BridgeState = {
    warmupCsvTimestamps: Object.fromEntries(
      Array.from(warmupCsvTimestamps.entries(), ([k, { value, storedAt }]) => [
        k,
        { csvMtime: value.csvMtime, cachedAt: storedAt },
      ]),
    ),
    lastWarmupAt,
    warmupCycleCounter,
    warmupCacheHits: { ...warmupCacheHits },
    warmupCacheMisses: { ...warmupCacheMisses },
    engineVersionCache,
    csvByteCache: Object.fromEntries(csvByteCache),
    csvStaticMtimes: Object.fromEntries(csvStaticMtimes),
    mt5ProcessLastResult,
  };
  try {
    await writeFile(path, JSON.stringify(state), "utf8");
  } catch {
    // Best-effort — state is non-critical
  }
}

// Load persisted bridge state on module initialization so that warmup
// caches survive Next.js hot reloads. This prevents 4 unnecessary Python
// subprocess calls (2 symbols × 2 modes) after every file change.
loadBridgeState();

let preparedCallWarmupPromise: Promise<void> | null = null;
let preparedCallWarmupTimer: ReturnType<typeof setTimeout> | null = null;
let manualCallGate: Promise<void> | null = null;

// Connection health tracking
let lastWarmupAt: string | null = null;
let mt5LastConnectedAt: string | null = null;

// ── MT5 auto-retry with exponential backoff ─────────────────
// When the MT5 terminal is running but the connection is stale
// (no successful test in the last 30s), automatically retry the
// connection. Uses exponential backoff: 30s → 60s → 120s → 240s
// (max 5 minutes). Resets on success.
const MT5_RETRY_BASE_MS = 30_000;
const MT5_RETRY_MAX_MS = 300_000; // 5 minutes
let mt5RetryState = {
  consecutiveFailures: 0,
  lastAttemptAt: 0, // epoch ms
  nextRetryAt: 0,   // epoch ms
  inProgress: false,
  lastResult: null as { success: boolean; error: string | null; duration_ms: number } | null,
};

function getMt5RetryBackoffMs(): number {
  const { consecutiveFailures } = mt5RetryState;
  if (consecutiveFailures <= 0) return MT5_RETRY_BASE_MS;
  // Exponential backoff: base * 2^(failures-1), capped at max
  return Math.min(
    MT5_RETRY_BASE_MS * Math.pow(2, consecutiveFailures - 1),
    MT5_RETRY_MAX_MS,
  );
}

/**
 * Check whether an automatic MT5 reconnection attempt should be triggered.
 * Returns true if:
 * - MT5 is configured (credentials in .env.local)
 * - MT5 terminal process is running (terminal64.exe detected)
 * - Connection is stale (no successful test in the last 30s)
 * - No retry is currently in progress
 * - Enough time has passed since the last attempt (respecting backoff)
 */
async function shouldRetryMt5(): Promise<boolean> {
  const cfg = getConfiguredLivePropProfile();
  if (!cfg) return false; // MT5 not configured

  const running = await isMt5ProcessRunning();
  if (!running) return false; // Terminal not running

  // Check if connection is stale (no successful test in 30s)
  if (mt5LastConnectedAt) {
    const elapsed = Date.now() - new Date(mt5LastConnectedAt).getTime();
    if (elapsed < MT5_RETRY_BASE_MS) return false; // Recently connected
  }

  // Check backoff
  if (mt5RetryState.inProgress) return false; // Already retrying
  if (Date.now() < mt5RetryState.nextRetryAt) return false; // Backoff active

  return true;
}

/**
 * Execute an automatic MT5 reconnection attempt with exponential backoff.
 * Called from getHealthMetrics() on each 15-second poll cycle.
 * Fire-and-forget — doesn't block the health response.
 */
function triggerMt5AutoRetry(): void {
  if (mt5RetryState.inProgress) return;

  mt5RetryState.inProgress = true;
  mt5RetryState.lastAttemptAt = Date.now();

  // Fire-and-forget — don't await, let it run in background
  retryMt5Connection().then((result) => {
    mt5RetryState.lastResult = {
      success: result.success,
      error: result.error,
      duration_ms: result.duration_ms,
    };

    if (result.success) {
      // Reset backoff on success
      mt5RetryState.consecutiveFailures = 0;
      mt5RetryState.nextRetryAt = 0;
    } else {
      // Increment failures and set next retry time
      mt5RetryState.consecutiveFailures += 1;
      mt5RetryState.nextRetryAt = Date.now() + getMt5RetryBackoffMs();
    }
  }).catch((err) => {
    console.warn("[mt5-auto-retry] Retry failed:", err instanceof Error ? err.message : err);
    mt5RetryState.consecutiveFailures += 1;
    mt5RetryState.nextRetryAt = Date.now() + getMt5RetryBackoffMs();
    mt5RetryState.lastResult = {
      success: false,
      error: "Auto-retry failed",
      duration_ms: 0,
    };
  }).finally(() => {
    mt5RetryState.inProgress = false;
  });
}

/**
 * Get the current MT5 auto-retry status for the frontend.
 * Called from getHealthMetrics() to include retry state in the response.
 */
function getMt5AutoRetryStatus() {
  return {
    consecutive_failures: mt5RetryState.consecutiveFailures,
    last_attempt_at: mt5RetryState.lastAttemptAt || null,
    next_retry_at: mt5RetryState.nextRetryAt || null,
    in_progress: mt5RetryState.inProgress,
    backoff_ms: getMt5RetryBackoffMs(),
    last_result: mt5RetryState.lastResult,
  };
}

/**
 * Warmup cycle counter — increments on every completed warmup pass.
 * Used to periodically trigger a live-tick collection (every 10th cycle)
 * instead of always using CSV-only mode. This keeps the CSV velocity
 * positive during idle periods without requiring manual calls.
 */
let warmupCycleCounter = 1;

// ── Append-only CSV byte-offset cache ──────────────────────────
// Instead of re-reading the entire 100K-tick CSV file on every
// warmup, we store the last-known byte offset and tick count per
// file path. On each read we only parse new lines appended at the
// tail — the CSV is append-only (live ticks are never inserted
// mid-file), so this is always correct. If the file shrinks
// (truncation or rotation), the cache resets automatically.
type CsvByteCache = {
  byteOffset: number;
  tickCount: number;
  mtime: number;
};
const csvByteCache = new Map<string, CsvByteCache>();

/** CSV byte-offset cache hit/miss counters — surfaceable via getHealthMetrics. */
let csvCacheHits = 0;
let csvCacheMisses = 0;


/**
 * Read only the tail of a CSV file that's been appended since the
 * last read. Returns the full line count (cached + new) and the
 * new byte offset for future reads.
 *
 * The `stat` call is intentionally NOT awaited in parallel with
 * `countCsvTicks`/`getHealthMetrics` — we need the mtime and size
 * before deciding how much to read, so sequential is correct.
 */
async function readCsvTail(
  csvPath: string,
): Promise<{ tickCount: number; byteOffset: number; mtime: number; contentLength: number }> {
  const s = await stat(csvPath);
  const fileSize = s.size;
  const mtime = s.mtimeMs;
  const prev = csvByteCache.get(csvPath);

  // File shrunk or no cache — full read from start
  if (!prev || fileSize < prev.byteOffset) {
    csvCacheMisses += 1;
    const content = await readFile(csvPath, "utf8");
    const lines = content.trim().split(/\r?\n/).filter(Boolean);
    const tickCount = lines.length;
    csvByteCache.set(csvPath, { byteOffset: fileSize, tickCount, mtime });
    return { tickCount, byteOffset: fileSize, mtime, contentLength: content.length };
  }

  // Size unchanged — return cached count
  if (fileSize === prev.byteOffset && mtime === prev.mtime) {
    csvCacheHits += 1;
    return { tickCount: prev.tickCount, byteOffset: prev.byteOffset, mtime, contentLength: fileSize };
  }

  csvCacheMisses += 1;

  // File grew — read ONLY the new bytes from disk by seeking to the
  // previous byte offset. This avoids reading the entire 4MB file and
  // then slicing in JS — true I/O-level optimization for the hot poll path.
  const handle = await open(csvPath, "r");
  try {
    const tailLength = fileSize - prev.byteOffset;
    const buf = Buffer.allocUnsafe(tailLength);
    const { bytesRead } = await handle.read(buf, 0, tailLength, prev.byteOffset);
    const tail = buf.toString("utf8", 0, bytesRead);
    const newLines = tail.trim().split(/\r?\n/).filter(Boolean);
    const tickCount = prev.tickCount + newLines.length;
    csvByteCache.set(csvPath, { byteOffset: fileSize, tickCount, mtime });
    return { tickCount, byteOffset: fileSize, mtime, contentLength: fileSize };
  } finally {
    await handle.close();
  }
}

// ── Shared Python MT5 context manager ────────────────────────
// Every Python subprocess that calls mt5.initialize() MUST use this
// helper to guarantee mt5.shutdown() is called on every exit path.
// The context manager handles initialize, login (if credentials given),
// and shutdown. The caller just does `with _mt5(...) as mt5:` and uses
// mt5.* normally inside the block.
const MT5_CTX = `
import contextlib as _ctx
import threading as _thr

def _init_with_timeout(tp, portable, timeout=10.0):
    """Run mt5.initialize in a daemon thread with a timeout.

    mt5.initialize() is a C-level call that can hang for 25+ seconds
    when the terminal is unresponsive (e.g., IPC deadlock). Wrapping it
    in a threaded join with timeout ensures the subprocess bails fast
    — never more than ~12s total even on the fallback path.
    """
    _r = {"ok": False, "error": None}
    def _run():
        try:
            ok = mt5.initialize(path=tp, portable=portable, timeout=8000) if tp else mt5.initialize(portable=portable, timeout=8000)
            _r["ok"] = ok
            if not ok:
                _r["error"] = mt5.last_error()
        except Exception as ex:
            _r["error"] = str(ex)
    t = _thr.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise RuntimeError(f"init_timed_out(portable={portable},timeout={timeout}s)")
    if not _r["ok"]:
        raise RuntimeError(_r["error"] or "init_false")

@_ctx.contextmanager
def _mt5(tp=None, lg=None, pw=None, sv=None):
    """MT5 connection context manager with fallback init strategy.

    Tries portable=False first (connects to an already-running terminal
    — fast, typically sub-second). If that fails (e.g., terminal not
    running), falls back to portable=True (starts a new instance).

    Each init attempt has a 10-second timeout via _init_with_timeout.
    """
    initialized = False
    init_error = None
    for portable in (False, True):
        for _ in range(2):
            try:
                _init_with_timeout(tp, portable, timeout=10.0)
                initialized = True
                break
            except Exception as ex:
                init_error = str(ex)
        if initialized:
            break
    if not initialized:
        raise RuntimeError(f"init:{init_error}")
    try:
        if lg is not None:
            if not mt5.login(int(lg), password=pw, server=sv):
                raise RuntimeError(f"login:{mt5.last_error()}")
        yield
    finally:
        mt5.shutdown()
`;

// ── Fresh call result cache (10s TTL) ────────────────────────
// Stores the last FreshCallResponse per (symbol, tradingMode, accountMode)
// so that rapid polls within the same window (e.g. frontend every 10s +
// guardian every 15s) reuse the fresh result without re-spawning Python.
// Key: "${symbol}_${tradingMode}_${accountMode}".
const FRESH_CALL_TTL_MS = 10_000;
const freshCallCache = createTtlCache<FreshCallResponse>(FRESH_CALL_TTL_MS);

// ── Warmup CSV-change cache (mtime only) ─────────────────────
// Tracks the last-seen CSV modification time per (symbol,tradingMode)
// across warmup cycles for the prepared-call re-use decision.
// Entries expire after 30 seconds (lazy eviction on get()).
const warmupCsvTimestamps = createTtlCache<{ csvMtime: number }>(30_000);

/**
 * Per-symbol CSV mtime monitor for the manual-call static-check path.
 *
 * Maps symbol → { mtime, seenAt } where `seenAt` is the wall-clock epoch
 * when `mtime` was first observed. When `isCsvStaticSinceMs()` finds that
 * the current mtime matches the stored entry AND the entry is at least N
 * seconds old, we know the CSV hasn't been touched for at least N seconds.
 *
 * Separate from `warmupCsvTimestamps` because the warmup cache tracks
 * (symbol,tradingMode) tuples with a 30s expiry — the static check needs
 * its own stable reference that persists between warmup cycles.
 */
const csvStaticMtimes = new Map<string, { mtime: number; seenAt: number }>();

/**
 * Warmup cache hit/miss counters — tracked per-symbol so the health dashboard
 * can show whether R_75 vs R_100 CSV files change at different rates.
 * Reset on server start, readable via getHealthMetrics.
 */
let warmupCacheHits: Record<string, number> = { R_75: 0, R_100: 0 };
let warmupCacheMisses: Record<string, number> = { R_75: 0, R_100: 0 };

// ── Test overrides ───────────────────────────────────────────
// All test-only overrides live on a single module-scoped object so that
// tests can set multiple overrides in one assignment without calling
// individual setter functions, and reset everything to defaults in one
// call from afterEach.

export type TestOverrides = {
  /** Override for isMt5ProcessRunning — tests set this to avoid real tasklist I/O. */
  isMt5ProcessRunning: () => Promise<boolean>;
};

const testOverrides: Partial<TestOverrides> = {};

export { testOverrides };

/**
 * Reset all test overrides and caches to their module-default state.
 * Call this in afterEach to ensure no override leaks between tests.
 */
export function resetTestOverrides(): void {
  delete testOverrides.isMt5ProcessRunning;
  warmupCsvTimestamps.clear();
  freshCallCache.clear();
  warmupCacheHits = { R_75: 0, R_100: 0 };
  warmupCacheMisses = { R_75: 0, R_100: 0 };
}

/**
 * Read the current warmup-cache hit/miss counters per symbol.
 * Returns a breakdown by symbol so tests can verify each symbol's
 * cache behaviour independently.
 */
export function getWarmupCacheStats(): {
  R_75: { hits: number; misses: number };
  R_100: { hits: number; misses: number };
} {
  return {
    R_75: { hits: warmupCacheHits.R_75 ?? 0, misses: warmupCacheMisses.R_75 ?? 0 },
    R_100: { hits: warmupCacheHits.R_100 ?? 0, misses: warmupCacheMisses.R_100 ?? 0 },
  };
}

/**
 * Full warmup cache state — returns the per-symbol hit/miss counters and
 * the raw CSV mtime timestamps map. Used by GET /api/system/warmup-cache
 * for debugging cache behaviour without the full health payload.
 */
export function getWarmupCacheState(): {
  hits: Record<string, number>;
  misses: Record<string, number>;
  csvTimestamps: Array<{ key: string; csvMtime: number; cachedAt: number; ageMs: number }>;
} {
  const now = Date.now();
  const timestamps: Array<{ key: string; csvMtime: number; cachedAt: number; ageMs: number }> = [];
  for (const [key, { value, storedAt }] of warmupCsvTimestamps.entries()) {
    timestamps.push({
      key,
      csvMtime: value.csvMtime,
      cachedAt: storedAt,
      ageMs: now - storedAt,
    });
  }
  return {
    hits: { ...warmupCacheHits },
    misses: { ...warmupCacheMisses },
    csvTimestamps: timestamps,
  };
}

// Engine version cache â€” read once via Python subprocess, cached forever.
// The version doesn't change during a server session.
let engineVersionCache: string | null | undefined = undefined;

/**
 * Cached result of the last MT5 process check — persists across
 * hot reloads via bridge_state.json. null means never checked.
 *
 * The cache avoids spawning `tasklist` on every 15-second poll
 * cycle. On each call, the real implementation re-checks and
 * updates this value. The persisted state from bridge_state.json
 * is only used as the starting value after a hot reload — the
 * first call to getConnectionStatus() after reload will re-check.
 */
let mt5ProcessLastResult: boolean | null = null;

/** Check whether the MT5 terminal64 process is currently running on Windows. */
/** @private real implementation — captured by the isMt5ProcessRunning let variable below. */
async function _realIsMt5ProcessRunning(): Promise<boolean> {
  try {
    const { stdout } = await execFileAsync("tasklist", ["/NH", "/FO", "CSV", "/FI", "IMAGENAME eq terminal64.exe"], {
      timeout: 3000,
      windowsHide: true,
    });
    const running = stdout.includes("terminal64.exe");
    mt5ProcessLastResult = running;
    return running;
  } catch {
    mt5ProcessLastResult = false;
    return false;
  }
}

/**
 * MT5 process-running check.
 *
 * Checks testOverrides.isMt5ProcessRunning first — tests set this to
 * avoid real tasklist I/O without calling individual setter functions.
 * Falls back to the real tasklist-based implementation when no override
 * is active.
 *
 * All internal callers reference this function directly, so the override
 * works for module-scoped calls — unlike vi.spyOn on the export which
 * only intercepts external callers.
 */
async function _overrideAwareIsMt5ProcessRunning(): Promise<boolean> {
  if (testOverrides.isMt5ProcessRunning) {
    return testOverrides.isMt5ProcessRunning();
  }
  return _realIsMt5ProcessRunning();
}

const isMt5ProcessRunning: () => Promise<boolean> = _overrideAwareIsMt5ProcessRunning;

export { isMt5ProcessRunning };

/** Count tick lines in CSV files for one or both symbols. */
export async function countCsvTicks(engineRoot: string): Promise<Record<string, number>> {
  const counts: Record<string, number> = { R_75: 0, R_100: 0 };

  for (const symbol of ["R_75", "R_100"] as const) {
    const candidates = [
      join(engineRoot, "data", `${symbol}_ticks.csv`),
      join(engineRoot, "data", `${symbol.toLowerCase().replace("_", "")}_ticks.csv`),
      join(engineRoot, "data", `${symbol.toUpperCase()}_ticks.csv`),
    ];
    for (const csvPath of candidates) {
      try {
        const { tickCount } = await readCsvTail(csvPath);
        counts[symbol] = tickCount;
        break;
      } catch {
        continue;
      }
    }
  }
  return counts;
}

/** Get a full connection-health snapshot. */
export async function getConnectionStatus(): Promise<{
  mt5_configured: boolean;
  mt5_process_running: boolean;
  engine_root_configured: boolean;
  csv_ticks: Record<string, number>;
  last_warmup_at: string | null;
  engine_bridge_version: number;
  engine_version: string | null;
  mt5_last_error: string | null;
  mt5_last_connected_at: string | null;
  mt5_last_test: {
    success: boolean;
    error: string | null;
    server: string | null;
    terminal_path: string | null;
    duration_ms: number;
    account_name: string | null;
    account_balance: number | null;
    tested_at: string;
  } | null;
}> {
  const engineRoot = getConfiguredEngineRoot();
  const mt5Config = getConfiguredLivePropProfile();
  let csvTicks: Record<string, number> = { R_75: 0, R_100: 0 };
  let mt5Running = false;
  let engineVersion: string | null = null;
  let mt5LastError: string | null = null;
  let mt5LastTest: Mt5TestFileRecord | null = null;

  // ── Parallel health check ──────────────────────────────────
  // All five sub-calls are independent — CSV reads, engine version,
  // MT5 error file, last test file, and tasklist check don't share
  // any data or ordering requirement. Promise.all cuts the wall-clock
  // time from sequential sum to the single slowest call (~1-5s vs ~2-8s).
  //
  // countCsvTicks: file I/O (2 CSV files, cached byte offset)
  // readEngineVersion: in-memory cache hit after 1st call; 5s subprocess on 1st
  // readMt5LastError: reads mt5_last_error.json (disk)
  // readMt5LastTest: reads mt5_last_test.json (disk)
  // isMt5ProcessRunning: tasklist subprocess (~3s timeout)
  if (engineRoot || mt5Config) {
    const tasks: Promise<unknown>[] = [];
    if (engineRoot) {
      tasks.push(
        countCsvTicks(engineRoot).then((r) => { csvTicks = r; }),
        readEngineVersion(engineRoot).then((r) => { engineVersion = r; }),
        readMt5LastError(engineRoot).then((r) => { mt5LastError = r; }),
        readMt5LastTest(engineRoot).then((r) => { mt5LastTest = r; }),
      );
    }
    if (mt5Config) {
      tasks.push(
        isMt5ProcessRunning().then((r) => { mt5Running = r; }),
      );
    }
    await Promise.all(tasks);
  }

  return {
    mt5_configured: mt5Config !== null,
    mt5_process_running: mt5Running,
    engine_root_configured: engineRoot !== null,
    csv_ticks: csvTicks,
    last_warmup_at: lastWarmupAt,
    engine_bridge_version: 1,
    engine_version: engineVersion,
    mt5_last_error: mt5LastError,
    mt5_last_connected_at: mt5LastConnectedAt,
    mt5_last_test: mt5LastTest,
  };
}

/**
 * Collect connection health metrics by reading shared files written
 * by the Python backend. No subprocess needed â€” data is on disk.
 */
export async function getHealthMetrics(): Promise<{
  mt5_configured: boolean;
  mt5_server: string | null;
  mt5_error: string | null;
  mt5_timing: { init_ms: number; login_ms: number; total_ms: number; timestamp: number } | null;
  csv_size_bytes: number;
  csv_ticks: Record<string, number>;
  health_history: Array<{ timestamp: number; mt5_init_ms: number; mt5_login_ms: number; mt5_total_ms: number; csv_ticks: Record<string, number> }>;
  snapshot_phases: Record<string, unknown> | null;
  engine_version: string | null;
  timestamp: number;
  warmup_cache_hits: Record<string, number>;
  warmup_cache_misses: Record<string, number>;
  csv_cache_hit_ratio: number;
  last_warmup_at: string | null;
  bridge_unavailable: boolean;
  pipeline_diagnostics: {
    lastGuardianReason: string | null;
    lastStderr: string | null;
    lastRetryCount: number;
    lastError: string | null;
    lastUpdatedAt: string | null;
    staleDataSince: number | null;
  };
  mt5_process_running: boolean;
  mt5_last_connected_at: string | null;
  mt5_last_test: {
    success: boolean;
    error: string | null;
    server: string | null;
    terminal_path: string | null;
    duration_ms: number;
    account_name: string | null;
    account_balance: number | null;
    tested_at: string;
  } | null;
  mt5_auto_retry: {
    consecutive_failures: number;
    last_attempt_at: number | null;
    next_retry_at: number | null;
    in_progress: boolean;
    backoff_ms: number;
    last_result: { success: boolean; error: string | null; duration_ms: number } | null;
  };
}> {
  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return {
      mt5_configured: false,
      mt5_server: null, mt5_error: null, mt5_timing: null,
      csv_size_bytes: 0, csv_ticks: { R_75: 0, R_100: 0 },
      health_history: [],
      snapshot_phases: null,
      engine_version: null, timestamp: Date.now(),
      warmup_cache_hits: { ...warmupCacheHits },
      warmup_cache_misses: { ...warmupCacheMisses },
      csv_cache_hit_ratio: 0,
      last_warmup_at: null,
      bridge_unavailable: false,
      pipeline_diagnostics: {
        lastGuardianReason: null, lastStderr: null,
        lastRetryCount: 0, lastError: null, lastUpdatedAt: null,
        staleDataSince: null,
      },
      mt5_process_running: false,
      mt5_last_connected_at: null,
      mt5_last_test: null,
      mt5_auto_retry: {
        consecutive_failures: 0, last_attempt_at: null, next_retry_at: null,
        in_progress: false, backoff_ms: MT5_RETRY_BASE_MS, last_result: null,
      },
    };
  }

  // Read mt5_timing.json â€” written by mt5_data.py on successful connection
  let mt5Timing: { init_ms: number; login_ms: number; total_ms: number; timestamp: number } | null = null;
  try {
    const raw = await readFile(join(engineRoot, "data", "mt5_timing.json"), "utf8");
    mt5Timing = JSON.parse(raw) as typeof mt5Timing;
  } catch { /* file not written yet */ }

  // Read mt5_last_error.json â€” written by mt5_data.py on connection failure
  let mt5Error: string | null = null;
  try {
    const raw = await readFile(join(engineRoot, "data", "mt5_last_error.json"), "utf8");
    const parsed = JSON.parse(raw) as { error?: string };
    if (typeof parsed.error === "string") mt5Error = parsed.error;
  } catch { /* no error */ }

  // Read engine version (cached after first subprocess call)
  const engineVersion = await readEngineVersion(engineRoot);

  // Count CSV ticks per symbol for velocity tracking
  // Uses the append-only byte-offset cache — only parses new lines
  // appended since the last read, so repeated polling never re-reads
  // the entire ~100K-tick file.
  const csvTicks: Record<string, number> = {};
  let csvSizeBytes = 0;
  for (const symbol of ["R_75", "R_100"] as const) {
    const candidates = [
      join(engineRoot, "data", `${symbol}_ticks.csv`),
      join(engineRoot, "data", `${symbol.toLowerCase().replace("_", "")}_ticks.csv`),
    ];
    let symbolCount = 0;
    for (const csvPath of candidates) {
      try {
        const { tickCount, contentLength } = await readCsvTail(csvPath);
        symbolCount = tickCount;
        csvSizeBytes += contentLength;
        break;
      } catch { continue; }
    }
    csvTicks[symbol] = symbolCount;
  }

  // Persist health sample to rolling history file (last 60 samples = ~15 min at 15s polls)
  const MAX_HEALTH_HISTORY = 60;
  const historyPath = join(engineRoot, "data", "health_history.json");
  let healthHistory: Array<{
    timestamp: number;
    mt5_init_ms: number;
    mt5_login_ms: number;
    mt5_total_ms: number;
    csv_ticks: Record<string, number>;
  }>;
  try {
    const raw = await readFile(historyPath, "utf8");
    healthHistory = JSON.parse(raw) as Array<{timestamp:number;mt5_init_ms:number;mt5_login_ms:number;mt5_total_ms:number;csv_ticks:Record<string,number>}>;
    if (!Array.isArray(healthHistory)) healthHistory = [];
  } catch {
    // File doesn't exist yet — start fresh
    healthHistory = [];
  }
  // Append current sample
  const ts = mt5Timing as { init_ms: number; login_ms: number; total_ms: number } | null;
  healthHistory.push({
    timestamp: Date.now(),
    mt5_init_ms: ts?.init_ms ?? 0,
    mt5_login_ms: ts?.login_ms ?? 0,
    mt5_total_ms: ts?.total_ms ?? 0,
    csv_ticks: { ...csvTicks },
  });
  // Trim to last 60 samples
  if (healthHistory.length > MAX_HEALTH_HISTORY) {
    healthHistory = healthHistory.slice(healthHistory.length - MAX_HEALTH_HISTORY);
  }
  try {
    await writeFile(historyPath, JSON.stringify(healthHistory), "utf8");
  } catch {
    // Best-effort — history is non-critical
  }

  // Read snapshot phase timing (written by executePythonSnapshot after each call)
  let snapshotPhases: Record<string, unknown> | null = null;
  try {
    const raw = await readFile(join(engineRoot, "data", "snapshot_phases.json"), "utf8");
    snapshotPhases = JSON.parse(raw) as Record<string, unknown>;
  } catch { /* file not written yet */ }

  // getPipelineDiagnostics() now calls clearStalePipelineErrors() internally,
  // so stale errors from past failures are automatically cleared when a
  // recent successful subprocess is observed. No duplicate logic needed here.
  const diagnostics = getPipelineDiagnostics();

  // Bridge-unavailable detection:
  // The bridge is unreachable when the engine root is configured but the
  // Python subprocess consistently fails. This covers:
  // - Subprocess timeout (35s timeout exceeded)
  // - ImportError / SyntaxError in the Python engine
  // - MT5 connection failure with no fallback
  // When bridge_unavailable is true, the HealthDashboard shows "Bridge Offline"
  // instead of "Critical" — a more accurate description of the root cause,
  // since zero velocity and stalled ticks are symptoms, not the problem.
  const bridge_unavailable = getConfiguredEngineRoot() !== null
    && diagnostics.lastError !== null;

  // ── MT5 process check, last test, and auto-retry (parallel reads) ──
  let mt5Running = false;
  let mt5LastTest: Mt5TestFileRecord | null = null;
  const mt5Config = getConfiguredLivePropProfile();
  if (mt5Config) {
    await Promise.all([
      isMt5ProcessRunning().then((r) => { mt5Running = r; }),
      readMt5LastTest(engineRoot).then((r) => { mt5LastTest = r; }),
    ]);

    // Auto-retry stale MT5 connection with exponential backoff.
    // Fire-and-forget — doesn't block the health response.
    // Uses the already-known mt5Running flag to avoid a redundant tasklist call.
    const lastTestOk = mt5LastTest != null && (mt5LastTest as Mt5TestFileRecord).success;
    if (mt5Running && !lastTestOk && !mt5RetryState.inProgress && Date.now() >= mt5RetryState.nextRetryAt) {
      triggerMt5AutoRetry();
    }
  }

  return {
    mt5_configured: mt5Config !== null,
    mt5_server: process.env.SYNTHETIC_MT5_SERVER?.trim() ?? null,
    mt5_error: mt5Error,
    mt5_timing: mt5Timing,
    mt5_process_running: mt5Running,
    mt5_last_connected_at: mt5LastConnectedAt,
    mt5_last_test: mt5LastTest,
    mt5_auto_retry: getMt5AutoRetryStatus(),
    csv_size_bytes: csvSizeBytes,
    csv_ticks: csvTicks,
    health_history: healthHistory,
    snapshot_phases: snapshotPhases,
    engine_version: engineVersion,
    timestamp: Date.now(),
    warmup_cache_hits: { ...warmupCacheHits },
    warmup_cache_misses: { ...warmupCacheMisses },
    csv_cache_hit_ratio: csvCacheHits + csvCacheMisses > 0
      ? Math.round((csvCacheHits / (csvCacheHits + csvCacheMisses)) * 100) / 100
      : 0,
    last_warmup_at: lastWarmupAt,
    bridge_unavailable,
    pipeline_diagnostics: diagnostics,
  };
}

/** Read the Python engine version string from the synthetic_trader package.
 *
 * Results are cached in-memory after the first successful read so that
 * the 15-second polling loops in ConnectionStatus and HealthDashboard
 * never spawn a subprocess on subsequent calls.
 */
async function readEngineVersion(engineRoot: string): Promise<string | null> {
  // Cache hit â€” return immediately without spawning.
  if (engineVersionCache !== undefined) {
    return engineVersionCache;
  }

  try {
    const { stdout } = await runPythonScript({
      engineRoot,
      pythonScript: `import json; from synthetic_trader import __version__; print(json.dumps(__version__))`,
      timeout: 5000,
      label: "readEngineVersion",
    });
    const version = JSON.parse(stdout.trim());
    if (typeof version === "string") {
      engineVersionCache = version;
      return version;
    }
  } catch {
    // runPythonScript already logs stderr via recordPipelineStderr
  }
  // Cache the failure so we don't keep retrying.
  engineVersionCache = null;
  return null;
}

/**
 * Test a live MT5 initialize + login and return the result.
 * Launches a Python subprocess that tries to connect and reports
 * the exact error or a success confirmation.
 */
export async function testMt5Connection(): Promise<{
  success: boolean;
  error: string | null;
  server: string | null;
  terminal_path: string | null;
  duration_ms: number;
}> {
  return testMt5ConnectionInner(false);
}

/**
 * Retry MT5 connection â€” same as testMt5Connection, but also clears the
 * persisted mt5_last_error.json file on success so the error badge
 * disappears on the next ConnectionStatus poll.
 */
export async function calibrateEgarch(symbol: string, csvPath?: string): Promise<{
  success: boolean;
  symbol: string;
  convergence: boolean;
  observations: number;
  omega: number;
  alpha: number;
  beta: number;
  gamma: number;
  persistence: number;
  half_life: number;
  long_run_vol: number;
  realized_vol: number;
  vol_ratio: number;
  saved_path: string | null;
  error: string | null;
  duration_ms: number;
}> {
  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return { success: false, symbol, convergence: false, observations: 0, omega: 0, alpha: 0, beta: 0, gamma: 0, persistence: 0, half_life: 0, long_run_vol: 0, realized_vol: 0, vol_ratio: 0, saved_path: null, error: "Engine root not configured", duration_ms: 0 };
  }

  // Default CSV path: the symbol's tick CSV in the data directory
  const resolvedCsv = csvPath || join(engineRoot, "data", `${symbol}_ticks.csv`);
  const startedAt = Date.now();

  try {
    const { stdout } = await withImportCheck(
      engineRoot,
      () => runPythonScript({
        engineRoot,
        pythonScript: `import json, time
from synthetic_trader.models.garch_calibration import (
    calibrate_from_ticks_csv,
    save_calibrated_garch_state,
)

t = time.time()
result = calibrate_from_ticks_csv(
    csv_path=${JSON.stringify(resolvedCsv)},
    symbol=${JSON.stringify(symbol)},
)
saved = save_calibrated_garch_state(result, ${JSON.stringify(symbol)})
print(json.dumps({
    "success": True,
    "symbol": result.symbol,
    "convergence": result.convergence,
    "observations": result.n_observations,
    "omega": result.omega,
    "alpha": result.alpha,
    "beta": result.beta,
    "gamma": result.gamma,
    "persistence": result.persistence,
    "half_life": result.half_life,
    "long_run_vol": result.long_run_vol,
    "realized_vol": result.realized_vol,
    "vol_ratio": result.vol_ratio,
    "saved_path": str(saved),
    "error": None if result.convergence else result.message,
    "duration_ms": int((time.time() - t) * 1000),
}))`,
        timeout: 120000,
        label: "calibrateEgarch",
      }),
      "calibrateEgarch",
    );
    const parsed = JSON.parse(stdout.trim());
    return {
      success: parsed.success ?? false,
      symbol: parsed.symbol ?? symbol,
      convergence: parsed.convergence ?? false,
      observations: parsed.observations ?? 0,
      omega: parsed.omega ?? 0,
      alpha: parsed.alpha ?? 0,
      beta: parsed.beta ?? 0,
      gamma: parsed.gamma ?? 0,
      persistence: parsed.persistence ?? 0,
      half_life: parsed.half_life ?? 0,
      long_run_vol: parsed.long_run_vol ?? 0,
      realized_vol: parsed.realized_vol ?? 0,
      vol_ratio: parsed.vol_ratio ?? 0,
      saved_path: parsed.saved_path ?? null,
      error: parsed.error ?? null,
      duration_ms: parsed.duration_ms ?? (Date.now() - startedAt),
    };
  } catch (error) {
    return {
      success: false,
      symbol,
      convergence: false,
      observations: 0,
      omega: 0,
      alpha: 0,
      beta: 0,
      gamma: 0,
      persistence: 0,
      half_life: 0,
      long_run_vol: 0,
      realized_vol: 0,
      vol_ratio: 0,
      saved_path: null,
      error: error instanceof Error ? error.message : "Unknown calibration error",
      duration_ms: Date.now() - startedAt,
    };
  }
}

export async function retryMt5Connection(): Promise<{
  success: boolean;
  error: string | null;
  server: string | null;
  terminal_path: string | null;
  duration_ms: number;
}> {
  return testMt5ConnectionInner(true);
}

async function testMt5ConnectionInner(clearErrorOnSuccess: boolean): Promise<{
  success: boolean;
  error: string | null;
  server: string | null;
  terminal_path: string | null;
  duration_ms: number;
}> {
  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return { success: false, error: "Engine root not configured", server: null, terminal_path: null, duration_ms: 0 };
  }

  const cfg = getConfiguredLivePropProfile();
  if (!cfg) {
    return { success: false, error: "MT5 not configured (set SYNTHETIC_MT5_SERVER / LOGIN / PASSWORD)", server: null, terminal_path: null, duration_ms: 0 };
  }

  const startedAt = Date.now();
  try {
    const { stdout, durationMs } = await withImportCheck(engineRoot,
      () => runPythonScript({
        engineRoot,
        pythonScript: `import json,time,os,MetaTrader5 as mt5
${MT5_CTX}
t=time.time()
tp=os.environ.get("SYNTHETIC_MT5_TERMINAL_PATH","")
sv=os.environ.get("SYNTHETIC_MT5_SERVER","")
lg=int(os.environ.get("SYNTHETIC_MT5_LOGIN","0"))
pw=os.environ.get("SYNTHETIC_MT5_PASSWORD","")
r={"success":False,"error":None,"server":sv,"terminal_path":tp or None}
try:
    with _mt5(tp=tp,lg=lg,pw=pw,sv=sv):
        a=mt5.account_info()
        r.update({"success":True,"account_name":a.name if a else "unknown","account_balance":a.balance if a else 0.0})
except RuntimeError as e:
    r["error"]=str(e)
except Exception as e:
    r["error"]="E: %s"%e
r["duration_ms"]=int((time.time()-t)*1000)
print(json.dumps(r))`,
        timeout: 20000,
        label: "testMt5Connection",
      }),
      "testMt5Connection",
    );
    const parsed = JSON.parse(stdout.trim()) as {
      success: boolean;
      error?: string;
      server?: string;
      terminal_path?: string | null;
      duration_ms?: number;
      account_name?: string;
      account_balance?: number;
    };

    // Persist test result to shared file so connection-status endpoint can
    // include it without a separate API call from the frontend.
    persistMt5TestResult(engineRoot, {
      success: parsed.success,
      error: parsed.error ?? null,
      server: parsed.server ?? null,
      terminal_path: parsed.terminal_path ?? null,
      duration_ms: parsed.duration_ms ?? durationMs,
      account_name: parsed.account_name ?? null,
      account_balance: parsed.account_balance ?? null,
    })

    // Record last successful connect timestamp so the UI can distinguish
    // "never connected" from "worked earlier but disconnected".
    if (parsed.success) {
      mt5LastConnectedAt = new Date().toISOString();
    }

    // Clear the persisted MT5 error file on successful retry so the
    // ConnectionStatus error badge disappears on the next poll cycle.
    if (clearErrorOnSuccess && parsed.success && engineRoot) {
      const errorPath = join(engineRoot, "data", "mt5_last_error.json");
      try {
        await writeFile(errorPath, JSON.stringify({ error: null }), "utf8");
      } catch {
        // Best-effort â€” the error badge will clear on next poll regardless
        // once mt5_data.py writes a clean connection status.
      }
    }

    return {
      success: parsed.success,
      error: parsed.error ?? null,
      server: parsed.server ?? null,
      terminal_path: parsed.terminal_path ?? null,
      duration_ms: parsed.duration_ms ?? durationMs,
      ...(parsed.account_name ? { account_name: parsed.account_name } : {}),
      ...(parsed.account_balance !== undefined ? { account_balance: parsed.account_balance } : {}),
    };
  } catch (error) {
    // runPythonScript already logs stderr via recordPipelineStderr
    const failure = {
      success: false,
      error: error instanceof Error ? error.message : "Unknown error",
      server: cfg.server ?? null,
      terminal_path: null,
      duration_ms: Date.now() - startedAt,
    };
    // Persist failure to shared file so connection-status can include it.
    persistMt5TestResult(engineRoot, { ...failure, account_name: null, account_balance: null });
    return failure;
  }
}

/** Read the persisted MT5 last-error file written by mt5_data.py. */
async function readMt5LastError(engineRoot: string): Promise<string | null> {
  const candidates = [
    join(engineRoot, "data", "mt5_last_error.json"),
  ];
  for (const filePath of candidates) {
    try {
      const raw = await readFile(filePath, "utf8");
      const parsed = JSON.parse(raw) as { error?: string };
      if (typeof parsed.error === "string") return parsed.error;
    } catch {
      continue;
    }
  }
  return null;
}
/** Write a structured test result to the shared file so the connection-status endpoint can include it. */
async function persistMt5TestResult(engineRoot: string | null, result: {
  success: boolean; error: string | null; server: string | null;
  terminal_path: string | null; duration_ms: number;
  account_name: string | null; account_balance: number | null;
}): Promise<void> {
  if (!engineRoot) return;
  const testPath = join(engineRoot, "data", "mt5_last_test.json");
  try {
    await writeFile(testPath, JSON.stringify({ ...result, tested_at: new Date().toISOString() }), "utf8");
  } catch {
    // Best-effort — the test result is still returned inline.
  }
}

async function readMt5LastTest(engineRoot: string): Promise<Mt5TestFileRecord | null> {
  try {
    const raw = await readFile(join(engineRoot, "data", "mt5_last_test.json"), "utf8");
    const parsed = JSON.parse(raw) as Mt5TestFileRecord;
    if (parsed && typeof parsed.success === "boolean") return parsed;
  } catch {
    return null;
  }
  return null;
}

/**
 * Get the mtime (ms) of a symbol's CSV tick file. Returns 0 if the
 * file doesn't exist, so an empty warmup cache slot is treated as
 * "definitely changed" on the first call.
 */
async function getSymbolCsvMtime(engineRoot: string, symbol: string): Promise<number> {
  const candidates = [
    join(engineRoot, "data", `${symbol}_ticks.csv`),
    join(engineRoot, "data", `${symbol.toLowerCase().replace("_", "")}_ticks.csv`),
  ];
  for (const csvPath of candidates) {
    try {
      const s = await stat(csvPath);
      return s.mtimeMs;
    } catch {
      continue;
    }
  }
  return 0;
}

/**
 * Check whether a symbol's CSV file has been unchanged for at least
 * `sinceMs` milliseconds.
 *
 * Uses `csvStaticMtimes` to track the first-seen mtime per symbol.
 * If the stored mtime matches the current mtime and it was first seen
 * at least `sinceMs` ago, returns true (no new ticks arrived).
 * If the mtime has changed (or no previous observation exists),
 * stores the new mtime and returns false.
 *
 * Returns false when the CSV file doesn't exist.
 */
async function isCsvStaticSinceMs(
  engineRoot: string,
  symbol: string,
  sinceMs: number,
): Promise<boolean> {
  const currentMtime = await getSymbolCsvMtime(engineRoot, symbol);
  if (currentMtime === 0) return false;

  const prev = csvStaticMtimes.get(symbol);
  const now = Date.now();

  if (!prev) {
    // First observation — store current mtime and return false.
    csvStaticMtimes.set(symbol, { mtime: currentMtime, seenAt: now });
    return false;
  }

  if (currentMtime !== prev.mtime) {
    // Mtime changed — update and return false.
    csvStaticMtimes.set(symbol, { mtime: currentMtime, seenAt: now });
    return false;
  }

  // Mtime unchanged — has it been stable long enough?
  return (now - prev.seenAt) >= sinceMs;
}

/**
 * Lightweight engine-status reader â€” returns the Python engine version
 * (from in-memory cache) and the MT5 error (from the disk file) without
 * spawning any subprocess on repeated calls.
 *
 * This is the dedicated endpoint used by ConnectionStatus and HealthDashboard
 * to avoid spawning a Python subprocess every 15 seconds just for the version string.
 */
export async function getEngineDiskStatus(engineRoot?: string | null): Promise<{
  engine_version: string | null;
  mt5_last_error: string | null;
}> {
  const root = engineRoot ?? getConfiguredEngineRoot();

  // Engine version â€” in-memory cache, populated on first call via readEngineVersion.
  // No subprocess spawned after the initial call.
  let engineVersion: string | null = null;
  if (root) {
    engineVersion = await readEngineVersion(root);
  }

  // MT5 last error â€” read from disk file written by mt5_data.py.
  let mt5LastError: string | null = null;
  if (root) {
    mt5LastError = await readMt5LastError(root);
  }

  return {
    engine_version: engineVersion,
    mt5_last_error: mt5LastError,
  };
}

// Track active Python snapshot child processes for cancellation
const activeSnapshotControllers = new Map<string, AbortController>();

/** Register an AbortController so the cancel endpoint can abort the Python process. */
export function registerLiveSnapshot(
  symbol: SymbolCode,
  tradingMode: TradingMode,
  controller: AbortController,
): void {
  const key = `${symbol}_${tradingMode}`;
  const existing = activeSnapshotControllers.get(key);
  if (existing && existing !== controller) {
    existing.abort();
  }
  activeSnapshotControllers.set(key, controller);
}

/** Unregister a controller (typically in a finally block). */
export function unregisterLiveSnapshot(
  symbol: SymbolCode,
  tradingMode: TradingMode,
): void {
  const key = `${symbol}_${tradingMode}`;
  activeSnapshotControllers.delete(key);
}

/** Abort and clean up a running Python snapshot process by symbol + trading mode. */
export function cancelLiveSnapshot(
  symbol: SymbolCode,
  tradingMode: TradingMode,
): void {
  const key = `${symbol}_${tradingMode}`;
  const controller = activeSnapshotControllers.get(key);
  if (controller) {
    controller.abort();
    activeSnapshotControllers.delete(key);
  }
}

export function getConfiguredEngineRoot() {
  const value = process.env.SYNTHETIC_ENGINE_ROOT?.trim();
  return value ? value : null;
}

function buildUnavailableBaseCall({
  symbol,
  detail,
}: {
  symbol: SymbolCode;
  detail: string;
}): BaseFreshCall {
  const message = `Live market read unavailable. ${detail}`;

  return {
    symbol,
    call: "stand_aside",
    alert_type: "context_update",
    trade_status: "not_valid",
    confidence: null,
    regime: null,
    direction_bias: null,
    why: message,
    wait_for: "wait for the live bridge to reconnect, then refresh the call",
    decision_summary: "Live market read unavailable. Refresh after the live bridge reconnects.",
    entry_area: null,
    stop_area: null,
    target_area: null,
    entry: null,
    stop_loss: null,
    take_profit: null,
    execution_stop: null,
    thesis_invalidation: null,
    primary_target: null,
    extended_target: null,
    hold_horizon_minutes: null,
    reward_risk: null,
    current_close: null,
    guardian_state: "unavailable",
    guardian_reason: message,
    invalidates_if: null,
    call_age_seconds: null,
    generated_at: new Date().toISOString(),
    raw_features: null,
    snapshot_structure: null,
    model_long_probability: null,
    trading_mode: null,
  };
}

function buildUnavailableFreshCall({
  symbol,
  accountMode,
  propAccountState,
  detail,
}: {
  symbol: SymbolCode;
  accountMode: AccountMode;
  propAccountState: PropAccountState | null;
  detail: string;
}): FreshCallResponse {
  const base = buildUnavailableBaseCall({ symbol, detail });

  return applyAccountMode({
    base,
    accountMode,
    propAccountState,
  });
}

/**
 * Build a fallback FreshCallResponse when the live Python subprocess fails.
 *
 * Tries the journal history first (most recent entry for the symbol).
 * When the journal is also empty, returns an explicit "unavailable" state
 * — no mock data, no fabricated trade plans. The user sees exactly what
 * went wrong.
 */
async function buildFallbackFreshCall({
  symbol,
  tradingMode,
  accountMode,
  propAccountState,
  detail,
}: {
  symbol: SymbolCode;
  tradingMode: TradingMode;
  accountMode: AccountMode;
  propAccountState: PropAccountState | null;
  detail: string;
}): Promise<FreshCallResponse> {
  // Try journal fallback first — reuse the most recent entry for this symbol.
  try {
    const entries = await readHistoryEntries(symbol, 1);
    const journalEntry = entries[0];
    if (
      journalEntry &&
      // Must have real analysis data — not just an unavailable stub
      (journalEntry.raw_features ||
       journalEntry.entry != null ||
       journalEntry.confidence != null)
    ) {
      const base = toBaseFreshCall(journalEntry);
      const refreshed = refreshCallAge({
        ...base,
        guardian_state: base.guardian_state === "unavailable" ? "forming" : base.guardian_state,
        guardian_reason: `Cached plan (${detail}) Last data: ${journalEntry.generated_at}.`,
        generated_at: new Date().toISOString(),
      });
      return applyAccountMode({
        base: sanitizeUnavailableExecutionLevels(refreshed),
        accountMode,
        propAccountState,
      });
    }
  } catch {
    // Journal read failed — fall through.
  }

  // No mock data — return explicit unavailable state.
  return buildUnavailableFreshCall({
    symbol,
    accountMode,
    propAccountState,
    detail: `${detail} No cached data found.`,
  });
}

function getEnvNumber(name: string, fallback: number): number {
  const parsed = Number(process.env[name] ?? "");
  return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : fallback;
}

function getManualSnapshotWarmupCount() {
  return getEnvNumber(
    "SYNTHETIC_ENGINE_COLD_WARMUP_COUNT",
    DEFAULT_COLD_SNAPSHOT_WARMUP_COUNT,
  );
}

function getPreparedSnapshotWarmupCount() {
  return getEnvNumber(
    "SYNTHETIC_ENGINE_PREPARED_WARMUP_COUNT",
    DEFAULT_PREPARED_SNAPSHOT_WARMUP_COUNT,
  );
}

function getManualSnapshotMaxLiveTicks() {
  return getEnvNumber(
    "SYNTHETIC_ENGINE_MAX_LIVE_TICKS",
    DEFAULT_MANUAL_SNAPSHOT_MAX_LIVE_TICKS,
  );
}

function getPreparedSnapshotMaxLiveTicks() {
  return getEnvNumber(
    "SYNTHETIC_ENGINE_PREPARED_MAX_LIVE_TICKS",
    DEFAULT_PREPARED_SNAPSHOT_MAX_LIVE_TICKS,
  );
}

function resolveSnapshotMaxLiveTicks(mode?: LiveSnapshotMode): number {
  return mode === "prepared"
    ? getPreparedSnapshotMaxLiveTicks()
    : getManualSnapshotMaxLiveTicks();
}

function getPreparedCallWarmupRefreshMs() {
  return getEnvNumber(
    "SYNTHETIC_ENGINE_PREPARED_WARMUP_REFRESH_MS",
    DEFAULT_PREPARED_CALL_WARMUP_REFRESH_MS,
  );
}

function getWarmupTickSampleCount() {
  return getEnvNumber(
    "SYNTHETIC_WARMUP_TICK_SAMPLE_COUNT",
    DEFAULT_WARMUP_TICK_SAMPLE_COUNT,
  );
}

function resolveSnapshotWarmupCount({
  mode,
  warmupProfile,
}: Pick<LiveSnapshotReadOptions, "mode" | "warmupProfile">): number {
  if (typeof warmupProfile?.warmupCount === "number" && warmupProfile.warmupCount > 0) {
    return Math.trunc(warmupProfile.warmupCount);
  }

  return mode === "prepared"
    ? getPreparedSnapshotWarmupCount()
    : getManualSnapshotWarmupCount();
}

async function readLiveSnapshotWithRetry({
  engineRoot,
  symbol,
  mode,
  warmupProfile,
  tradingMode,
  skipApi = false,
  signal,
}: LiveSnapshotReadOptions) {
  let lastError: unknown;
  let attempts = 0;

  for (let attempt = 0; attempt < LIVE_SNAPSHOT_MAX_ATTEMPTS; attempt += 1) {
    if (signal?.aborted) {
      throw new DOMException("Canceled", "AbortError");
    }
    try {
      const result = await liveSnapshotAdapter.read({ engineRoot, symbol, mode, warmupProfile, tradingMode, skipApi, signal });
      // On success, capture the guardian reason and clear any previous
      // error so `bridge_unavailable` resets on the next health poll.
      if (result.guardian_reason) {
        recordPipelineGuardianReason(result.guardian_reason);
      }
      recordPipelineRetry(attempt);
      recordPipelineError(null); // Clear stale error — bridge is working
      return result;
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw error;
      }
      if (signal?.aborted) {
        throw new DOMException("Canceled", "AbortError");
      }
      attempts = attempt + 1;
      lastError = error;
    }
  }

  // Record diagnostics on failure
  recordPipelineRetry(attempts);
  recordPipelineError(lastError instanceof Error ? lastError.message : String(lastError));
  throw lastError instanceof Error ? lastError : new Error("Unable to read live snapshot");
}

function applyAccountMode({
  base,
  accountMode,
  propAccountState,
}: {
  base: BaseFreshCall;
  accountMode: AccountMode;
  propAccountState: PropAccountState | null;
}): FreshCallResponse {

  if (accountMode === "own_account") {
    return freshCallResponseSchema.parse({
      ...base,
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    });
  }

  const compliance = evaluatePropCompliance({
    call: base,
    accountState: propAccountState,
    proposedRiskPercent: 1,
  });

  return freshCallResponseSchema.parse({
    ...base,
    account_mode: "prop_firm",
    prop_compliance: compliance.status,
    prop_adjusted_risk: compliance.adjustedRiskPercent,
    prop_block_reason: compliance.blockReason,
    prop_remaining_daily_buffer: compliance.remainingDailyBuffer,
    prop_remaining_overall_buffer: compliance.remainingOverallBuffer,
  });
}

export function toBaseFreshCall(call: FreshCallResponse): BaseFreshCall {
  return {
    symbol: call.symbol,
    call: call.call,
    alert_type: call.alert_type,
    trade_status: call.trade_status,
    confidence: call.confidence,
    regime: call.regime,
    direction_bias: call.direction_bias,
    why: call.why,
    wait_for: call.wait_for,
    decision_summary: normalizeText(call.decision_summary),
    entry_area: call.entry_area,
    stop_area: call.stop_area,
    target_area: call.target_area,
    entry: call.entry,
    stop_loss: call.stop_loss,
    take_profit: call.take_profit,
    execution_stop: call.execution_stop ?? null,
    thesis_invalidation: call.thesis_invalidation ?? null,
    primary_target: call.primary_target ?? null,
    extended_target: call.extended_target ?? null,
    hold_horizon_minutes: call.hold_horizon_minutes ?? null,
    reward_risk: call.reward_risk,
    current_close: call.current_close,
    guardian_state: call.guardian_state,
    guardian_reason: call.guardian_reason,
    invalidates_if: normalizeText(call.invalidates_if),
    call_age_seconds: call.call_age_seconds ?? null,
    generated_at: call.generated_at,
    raw_features: call.raw_features ?? null,
    snapshot_structure: call.snapshot_structure ?? null,
    model_long_probability: call.model_long_probability ?? null,
    trading_mode: call.trading_mode ?? null,
  };
}

export function refreshCallAge(base: BaseFreshCall): BaseFreshCall {
  const generatedAtMs = Date.parse(base.generated_at);
  if (Number.isNaN(generatedAtMs)) {
    return base;
  }

  return {
    ...base,
    call_age_seconds: Math.max(0, Math.floor((Date.now() - generatedAtMs) / 1000)),
  };
}

function getPreparedCallMaxAgeMs(call: FreshCallResponse): number {
  return call.guardian_state === "actionable" || call.guardian_state === "confirmed"
    ? PREPARED_CALL_ACTIONABLE_MAX_AGE_MS
    : PREPARED_CALL_TRANSIENT_MAX_AGE_MS;
}

function isPreparedCallFresh(call: FreshCallResponse): boolean {
  const generatedAtMs = Date.parse(call.generated_at);
  if (Number.isNaN(generatedAtMs)) {
    return false;
  }

  return Math.abs(Date.now() - generatedAtMs) <= getPreparedCallMaxAgeMs(call) && Date.now() >= generatedAtMs;
}

export function shouldReusePreparedCall(call: FreshCallResponse): boolean {
  if (!isPreparedCallFresh(call)) {
    return false;
  }

  return !(
    call.trade_status !== "valid" &&
    call.guardian_state === "forming" &&
    typeof call.confidence === "number" &&
    call.confidence >= PREPARED_CALL_NEAR_THRESHOLD_RECHECK_CONFIDENCE
  );
}

function normalizeNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
}

function normalizeText(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim();
  return normalized ? normalized : null;
}

function normalizeTradingMode(value: unknown): TradingMode | null {
  return value === "sniper" || value === "active_trader" ? value : null;
}

function normalizeGuardianState(
  value: unknown,
): BaseFreshCall["guardian_state"] {
  return value === "forming" ||
    value === "actionable" ||
    value === "confirmed" ||
    value === "failing" ||
    value === "cancelled" ||
    value === "unavailable"
    ? value
    : "unavailable";
}

function normalizeCallAgeSeconds(value: unknown): number | null {
  const normalized = normalizeNumber(value);
  if (normalized === null || normalized < 0) {
    return null;
  }

  return Math.trunc(normalized);
}

function normalizeDict(value: unknown): Record<string, number> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const result: Record<string, number> = {};
  for (const [k, v] of Object.entries(value)) {
    if (typeof v === "number" && Number.isFinite(v)) {
      result[k] = v;
    }
  }
  return Object.keys(result).length > 0 ? result : null;
}

function normalizeHoldHorizonMinutes(value: unknown): number | null {
  const normalized = normalizeNumber(value);
  if (normalized === null || normalized <= 0) {
    return null;
  }

  return Math.trunc(normalized);
}

function normalizeConnectionField(value: string | null | undefined) {
  return normalizeText(value ?? null);
}

function withTelemetry(
  profile: PropAccountState,
  telemetry: PropProfileResponse["telemetry"],
): PropProfileResponse {
  return {
    ...profile,
    telemetry,
  };
}

function classifyAlertType(call: BaseFreshCall["call"], tradeStatus: string) {
  return tradeStatus === "valid" && call !== "stand_aside"
    ? "setup_candidate"
    : "context_update";
}

function buildDecisionSummary(base: BaseFreshCall): string | null {
  if (base.trade_status !== "valid" || base.call === "stand_aside") {
    return null;
  }

  return `${base.call === "buy_candidate" ? "buy" : "sell"} setup ready; ${
    base.why ?? "the market structure is aligned"
  }`;
}

function mapLiveSnapshot(raw: Record<string, unknown>, symbol: SymbolCode): BaseFreshCall {
  const call =
    raw.call === "buy_candidate" ||
    raw.call === "sell_candidate" ||
    raw.call === "stand_aside"
      ? raw.call
      : "stand_aside";
  const tradeStatus = normalizeText(raw.trade_status) ?? "not_valid";
  const why =
    normalizeText(raw.why) ??
    normalizeText(raw.briefing) ??
    normalizeText(raw.decision_summary);

  const rawFeatures = normalizeDict(raw.raw_features);
  const snapshotStructure = normalizeDict(raw.snapshot_structure);

  const base: BaseFreshCall = {
    symbol,
    call,
    alert_type: normalizeText(raw.alert_type) ?? classifyAlertType(call, tradeStatus),
    trade_status: tradeStatus,
    confidence: normalizeNumber(raw.confidence),
    regime: normalizeText(raw.regime),
    direction_bias: normalizeText(raw.direction_bias),
    why,
    wait_for: normalizeText(raw.wait_for),
    decision_summary: normalizeText(raw.decision_summary),
    entry_area: normalizeText(raw.entry_area),
    stop_area: normalizeText(raw.stop_area),
    target_area: normalizeText(raw.target_area),
    entry: normalizeNumber(raw.entry),
    stop_loss: normalizeNumber(raw.stop_loss),
    take_profit: normalizeNumber(raw.take_profit),
    execution_stop: normalizeNumber(raw.execution_stop),
    thesis_invalidation: normalizeNumber(raw.thesis_invalidation),
    primary_target: normalizeNumber(raw.primary_target),
    extended_target: normalizeNumber(raw.extended_target),
    hold_horizon_minutes: normalizeHoldHorizonMinutes(raw.hold_horizon_minutes),
    reward_risk: normalizeNumber(raw.reward_risk),
    current_close: normalizeNumber(raw.current_close),
    guardian_state: normalizeGuardianState(raw.guardian_state),
    guardian_reason:
      normalizeText(raw.guardian_reason) ??
      "Live guardian state is unavailable.",
    invalidates_if: normalizeText(raw.invalidates_if),
    call_age_seconds: normalizeCallAgeSeconds(raw.call_age_seconds),
    generated_at: normalizeText(raw.generated_at) ?? new Date().toISOString(),
    raw_features: rawFeatures,
    snapshot_structure: snapshotStructure,
    model_long_probability: normalizeNumber(raw.model_long_probability),
    risk_state: typeof raw.risk_state === "object" && raw.risk_state !== null ? raw.risk_state as Record<string, unknown> : null,
    trading_mode: normalizeTradingMode(raw.trading_mode),
    signal_strength: normalizeText(raw.signal_strength) as FreshCallResponse["signal_strength"] ?? null,
    position_sizing: normalizeText(raw.position_sizing) as FreshCallResponse["position_sizing"] ?? null,
  };

  return {
    ...base,
    decision_summary: base.decision_summary ?? buildDecisionSummary(base),
  };
}

export function sanitizeUnavailableExecutionLevels(base: BaseFreshCall): BaseFreshCall {
  if (base.guardian_state !== "unavailable") {
    return base;
  }

  return {
    ...base,
    entry_area: null,
    stop_area: null,
    target_area: null,
    entry: null,
    stop_loss: null,
    take_profit: null,
    execution_stop: null,
    thesis_invalidation: null,
    primary_target: null,
    extended_target: null,
    hold_horizon_minutes: null,
    reward_risk: null,
  };
}

async function executePythonSnapshot({
  engineRoot,
  symbol,
  mode,
  warmupProfile,
  tradingMode,
  skipApi = true,
  signal,
}: {
  engineRoot: string;
  symbol: SymbolCode;
  mode?: LiveSnapshotMode;
  warmupProfile?: LiveSnapshotWarmupProfile;
  tradingMode?: TradingMode;
  skipApi?: boolean;
  signal?: AbortSignal;
}): Promise<BaseFreshCall> {
  const maxLiveTicks = resolveSnapshotMaxLiveTicks(mode);
  const warmupCount = resolveSnapshotWarmupCount({ mode, warmupProfile });
  const resolvedTradingMode = tradingMode ?? "sniper";
  const modelArtifact = join(engineRoot, "artifacts", `${symbol.toLowerCase()}_live_seed_model.json`);
  const escapedModelPath = JSON.stringify(modelArtifact);
  const pythonScript = `
import asyncio
import json
from pathlib import Path
from synthetic_trader.live.market_snapshot import build_watch_alert, run_live_snapshot
from synthetic_trader.models.online import OnlineLogisticModel

model = None
model_path = Path(${escapedModelPath})
if model_path.exists():
    try:
        model = OnlineLogisticModel.load(model_path)
    except Exception:
        model = None

try:
    snapshot = asyncio.run(
        run_live_snapshot(
            symbol="${symbol}",
            warmup_count=${warmupCount},
            timeframe_sec=60,
            higher_timeframe_sec=300,
            max_live_ticks=${Number.isFinite(maxLiveTicks) ? maxLiveTicks : 40},
            trading_mode="${resolvedTradingMode}",
            model_path=str(model_path) if model else None,
            skip_api=${skipApi ? "True" : "False"},
            app_id="${(process.env.DERIV_APP_ID || '').replace(/"/g, '')}",
        )
    )
    print(json.dumps(build_watch_alert(snapshot)))
except Exception as e:
    print(json.dumps({
        "call": "stand_aside",
        "symbol": "${symbol}",
        "trade_status": "not_valid",
        "direction_bias": "none",
        "regime": "unknown",
        "confidence": None,
        "current_close": None,
        "guardian_state": "unavailable",
        "guardian_reason": f"Snapshot error: {e}",
        "trading_mode": "${resolvedTradingMode}",
    }))
`.trim();

  const { stdout } = await runPythonScript({
    engineRoot,
    pythonScript,
    timeout: LIVE_SNAPSHOT_TIMEOUT_MS,
    label: "executePythonSnapshot",
    signal,
  });

  const parsed = JSON.parse(stdout.trim()) as Record<string, unknown>;

  // Capture stale_data_since from the Python snapshot for the pipeline diagnostics panel.
  if (parsed && typeof parsed === "object" && "stale_data_since" in parsed) {
    recordPipelineStaleDataSince(parsed["stale_data_since"] as number | null | undefined);
  }

  // Persist phase timing to a shared file so the health dashboard can
  // read it without a subprocess.
  if (parsed && typeof parsed === "object" && "phase_timing_ms" in parsed) {
    const rawPhaseTiming = parsed["phase_timing_ms"];
    if (rawPhaseTiming && typeof rawPhaseTiming === "object") {
      const phasePath = join(engineRoot, "data", "snapshot_phases.json");
      const out = JSON.stringify({ ...rawPhaseTiming as Record<string, unknown>, symbol, trading_mode: resolvedTradingMode, timestamp: Date.now() });
      writeFile(phasePath, out, "utf8").catch(() => {/* best-effort */});
    }
  }

  return mapLiveSnapshot(parsed, symbol);
}

export async function readLiveSnapshot({
  engineRoot,
    symbol,
    mode,
    warmupProfile,
    tradingMode,
    skipApi = true,
  signal,
  }: LiveSnapshotReadOptions): Promise<BaseFreshCall> {
  return await withImportCheck(engineRoot,
    () => executePythonSnapshot({
      engineRoot,
      symbol,
      mode,
      warmupProfile,
      tradingMode,
      skipApi,
      signal,
    }),
    "readLiveSnapshot",
  );
}

export const liveSnapshotAdapter = {
  read: readLiveSnapshot,
};

async function executePythonPropProfile({
  engineRoot,
  config,
}: {
  engineRoot: string;
  config: LivePropProfileConfig;
}): Promise<PropAccountState> {
  const escapedPassword = JSON.stringify(config.password);
  const escapedServer = JSON.stringify(config.server);
  const resolvedTerminal = config.terminalPath || resolveTerminalPath();
  const escapedTerminal = resolvedTerminal
    ? JSON.stringify(resolvedTerminal)
    : "None";
  const pythonScript = `
import json
from datetime import datetime
import MetaTrader5 as mt5
${MT5_CTX}
try:
    with _mt5(tp=${escapedTerminal},lg=int(${config.login}),pw=${escapedPassword},sv=${escapedServer}):
        account = mt5.account_info()
        if account is None:
            raise RuntimeError("mt5_account_info_missing")

        positions = mt5.positions_get() or []
        floating_loss = 0.0
        for position in positions:
            profit = float(getattr(position, "profit", 0.0) or 0.0)
            if profit < 0:
                floating_loss += abs(profit)

        start_of_day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        deals = mt5.history_deals_get(start_of_day, datetime.now()) or []
        realized_loss = 0.0
        for deal in deals:
            profit = float(getattr(deal, "profit", 0.0) or 0.0)
            if profit < 0:
                realized_loss += abs(profit)

        print(json.dumps({
            "currentBalance": float(account.balance),
            "currentEquity": float(account.equity),
            "todaysRealizedLoss": round(realized_loss, 2),
            "todaysFloatingLossExposure": round(floating_loss, 2),
        }))
except RuntimeError as e:
    print(json.dumps({
        "currentBalance": 0.0,
        "currentEquity": 0.0,
        "todaysRealizedLoss": 0.0,
        "todaysFloatingLossExposure": 0.0,
        "error": f"MT5 error: {e}",
    }))
except Exception as e:
    print(json.dumps({
        "currentBalance": 0.0,
        "currentEquity": 0.0,
        "todaysRealizedLoss": 0.0,
        "todaysFloatingLossExposure": 0.0,
        "error": f"Unexpected error in executePythonPropProfile: {e}",
    }))
`.trim();

  // executePythonPropProfile uses full process.env (not buildPythonChildEnv)
  // because MT5 login may need system-level env vars set by the host app.
  const { stdout } = await withImportCheck(engineRoot,
    () => runPythonScript({
      engineRoot,
      pythonScript,
      timeout: 20000,
      label: "executePythonPropProfile",
      extraEnv: {
        ...(process.env as Record<string, string>),
        PYTHONPATH: join(engineRoot, "src"),
        PYTHONDONTWRITEBYTECODE: "1",
      },
    }),
    "executePythonPropProfile",
  );

  const parsed = JSON.parse(stdout.trim()) as {
    currentBalance: number;
    currentEquity: number;
    todaysRealizedLoss: number;
    todaysFloatingLossExposure: number;
  };

  return {
    profile: config.profile,
    startingBalance: config.startingBalance,
    currentBalance: parsed.currentBalance,
    currentEquity: parsed.currentEquity,
    todaysRealizedLoss: parsed.todaysRealizedLoss,
    todaysFloatingLossExposure: parsed.todaysFloatingLossExposure,
    highImpactNewsLockout: config.highImpactNewsLockout,
  };
}

export async function readLivePropProfile({
  engineRoot,
  config,
}: {
  engineRoot: string;
  config: LivePropProfileConfig;
}): Promise<PropAccountState> {
  return await executePythonPropProfile({
    engineRoot,
    config,
  });
}

export const livePropProfileAdapter = {
  read: readLivePropProfile,
};

function getHistoryJournalPath() {
  const configured = process.env.SYNTHETIC_OPERATOR_HISTORY_PATH?.trim();
  return configured
    ? configured
    : `${process.cwd()}\\.data\\operator-call-history.jsonl`;
}

function getConfiguredLivePropProfile(): LivePropProfileConfig | null {
  const server = process.env.SYNTHETIC_MT5_SERVER?.trim();
  const login = process.env.SYNTHETIC_MT5_LOGIN?.trim();
  const password = process.env.SYNTHETIC_MT5_PASSWORD?.trim();
  const terminalPath = process.env.SYNTHETIC_MT5_TERMINAL_PATH?.trim() ?? null;
  const configuredStartingBalance = Number(process.env.SYNTHETIC_PROP_STARTING_BALANCE ?? "");
  const startingBalance = Number.isFinite(configuredStartingBalance)
    ? configuredStartingBalance
    : DEFAULT_PROP_STARTING_BALANCE;

  if (!server || !login || !password) {
    return null;
  }

  return {
    server,
    login,
    password,
    terminalPath,
    startingBalance,
    highImpactNewsLockout:
      String(process.env.SYNTHETIC_PROP_NEWS_LOCKOUT ?? "").toLowerCase() === "true",
    profile: "blueberry_2step_funded",
  };
}

function resolveRequestedPropConfig(
  request: PropProfileRequest | null | undefined,
): LivePropProfileConfig | null {
  const requestedServer = normalizeConnectionField(request?.connection?.server ?? null);
  const requestedLogin = normalizeConnectionField(request?.connection?.login ?? null);
  const requestedPassword = normalizeConnectionField(request?.connection?.password ?? null);
  const requestedTerminalPath = normalizeConnectionField(
    request?.connection?.terminalPath ?? null,
  );
  const requestedStartingBalance = Number.isFinite(request?.startingBalance)
    ? Number(request?.startingBalance)
    : Number.isFinite(request?.connection?.startingBalance)
      ? Number(request?.connection?.startingBalance)
      : DEFAULT_PROP_STARTING_BALANCE;

  if (requestedServer && requestedLogin && requestedPassword) {
    return {
      server: requestedServer,
      login: requestedLogin,
      password: requestedPassword,
      terminalPath: requestedTerminalPath,
      startingBalance: requestedStartingBalance,
      highImpactNewsLockout:
        String(process.env.SYNTHETIC_PROP_NEWS_LOCKOUT ?? "").toLowerCase() === "true",
      profile: "blueberry_2step_funded",
    };
  }

  const fallback = getConfiguredLivePropProfile();
  if (!fallback) {
    return null;
  }

  return {
    ...fallback,
    startingBalance: requestedStartingBalance,
  };
}

const MAX_OPERATOR_HISTORY_ENTRIES = 1000;

async function appendHistoryEntry(call: FreshCallResponse) {
  const journalPath = getHistoryJournalPath();
  await mkdir(dirname(journalPath), { recursive: true });
  await appendFile(journalPath, `${JSON.stringify(call)}\n`, "utf8");

  // ── Prune to MAX_OPERATOR_HISTORY_ENTRIES after each append ──
  // Rewrites the file with only the most recent N entries to prevent
  // unbounded growth from the 15-second polling loop.
  try {
    const st = await stat(journalPath).catch(() => null);
    if (!st || st.size < 100_000) return; // Skip if small enough
    const content = await readFile(journalPath, "utf8");
    const lines = content.split("\n").filter(Boolean);
    if (lines.length <= MAX_OPERATOR_HISTORY_ENTRIES) return;
    await writeFile(journalPath, lines.slice(-MAX_OPERATOR_HISTORY_ENTRIES).join("\n") + "\n", "utf8");
  } catch {
    // Best-effort; pruning should never crash the system.
  }
}

/** Max entries in operator-call-history.jsonl before pruning kicks in. */

export async function readHistoryEntries(symbol: SymbolCode, limit = DEFAULT_HISTORY_LIMIT) {
  try {
    const journalPath = getHistoryJournalPath();
    const contents = await readFile(journalPath, "utf8");
    const entries = contents
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .flatMap((line) => {
        try {
          return [freshCallResponseSchema.parse(JSON.parse(line))];
        } catch {
          return [];
        }
      })
      .filter((entry) => entry.symbol === symbol)
      .sort((left, right) => right.generated_at.localeCompare(left.generated_at));

    return entries.slice(0, limit);
  } catch {
    return [];
  }
}

export async function readPreparedCall(symbol: SymbolCode): Promise<BaseFreshCall | null> {
  const entries = await readHistoryEntries(symbol, 1);
  const latest = entries[0];
  if (!latest || !shouldReusePreparedCall(latest)) {
    return null;
  }

  return refreshCallAge(toBaseFreshCall(latest));
}

/**
 * Lightweight tick collector that runs after every warmup cycle.
 * Connects to MT5, collects 3-5 live ticks per symbol, and appends
 * them to the CSV file. This ensures the CSV slowly accumulates ticks
 * during idle periods â€” so the health dashboard shows a non-zero
 * velocity even when no manual calls are being made.
 *
 * The Python script is intentionally minimal: it connects, subscribes
 * for a small number of ticks, writes them to CSV, and shuts down.
 * No candle-building, regime analysis, or signal evaluation.
 */
async function collectWarmupTickSample({
  engineRoot,
  symbol,
}: {
  engineRoot: string;
  symbol: SymbolCode;
}): Promise<void> {
  const sampleCount = getWarmupTickSampleCount();
  const configuredServer = process.env.SYNTHETIC_MT5_SERVER?.trim() ?? "";
  const configuredLogin = process.env.SYNTHETIC_MT5_LOGIN?.trim() ?? "";
  const configuredPassword = process.env.SYNTHETIC_MT5_PASSWORD?.trim() ?? "";
  const configuredTerminal = process.env.SYNTHETIC_MT5_TERMINAL_PATH?.trim() ?? "";

  const pythonScript = `
import json
import time
import MetaTrader5 as mt5
from datetime import datetime, timedelta
from pathlib import Path
${MT5_CTX}
try:
    with _mt5(tp=${JSON.stringify(configuredTerminal || null)},lg=int(${configuredLogin}),pw=${JSON.stringify(configuredPassword)},sv=${JSON.stringify(configuredServer)}):
        # Resolve MT5 symbol — try Blueberry Markets name first, then fallbacks
        _vol = "75" if "${symbol}" == "R_75" else "100"
        _candidates = [
            f"Blueberry Volatility {_vol}",
            f"Volatility {_vol} Index",
            f"Volatility {_vol}",
            f"Vol {_vol} Index",
            f"Vol {_vol}",
            f"R_{_vol}",
        ]
        mt5_symbol = None
        for _name in _candidates:
            if mt5.symbol_info(_name) is not None:
                mt5_symbol = _name
                break
        if mt5_symbol is None:
            print(json.dumps({"collected": 0, "error": f"Symbol not found. Tried: {', '.join(_candidates)}"}))
            raise SystemExit(0)
        now = datetime.now()
        ticks = mt5.copy_ticks_from(mt5_symbol, now - timedelta(seconds=15), ${sampleCount})

        if ticks is None or len(ticks) == 0:
            print(json.dumps({"collected": 0, "error": None}))
            raise SystemExit(0)

        csv_candidates = [
            Path(f"data/${symbol}_ticks.csv"),
            Path(f"data/${symbol.toLowerCase().replace('_', '')}_ticks.csv"),
            Path(f"data/${symbol.toUpperCase()}_ticks.csv"),
        ]
        csv_path = next((p for p in csv_candidates if p.exists()), csv_candidates[0])

        with csv_path.open("a", encoding="utf-8") as f:
            for tick in ticks:
                f.write(f"{int(tick.time)},{tick.bid},{tick.ask}\\n")

        print(json.dumps({"collected": len(ticks), "error": None}))
except RuntimeError as e:
    print(json.dumps({"collected": 0, "error": str(e)}))
except Exception as e:
    print(json.dumps({"collected": 0, "error": str(e)}))
`.trim();

  try {
    await runPythonScript({
      engineRoot,
      pythonScript,
      timeout: 15000,
      label: "collectWarmupTickSample",
    });
  } catch {
    // Tick sampling is best-effort â€” never interrupt the warmup cycle.
  }
}

/**
 * Trigger a fresh tick collection for both symbols — connects to MT5,
 * grabs a small sample of live ticks per symbol, and appends them to
 * the CSV file. Returns a summary of what was collected.
 *
 * This is the lightweight "Collect Fresh Ticks" action surfaced in the
 * Pipeline Diagnostics panel — useful when CSV data is stale and the
 * user wants to kick-start the data pipeline without running a full
 * analysis snapshot.
 */
export async function collectFreshTicks(): Promise<{
  collected: number;
  errors: string[];
  duration_ms: number;
}> {
  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return { collected: 0, errors: ["Engine root not configured"], duration_ms: 0 };
  }

  const startedAt = Date.now();
  let totalCollected = 0;
  const errors: string[] = [];

  for (const symbol of PREPARED_CALL_WARMUP_SYMBOLS) {
    if (preparedCallWarmupPromise) {
      // Warmup already in flight — wait for it rather than duplicating work
      await preparedCallWarmupPromise;
      // We can't count what was collected during the warmup, so return a neutral result
      return { collected: -1, errors: [], duration_ms: Date.now() - startedAt };
    }
    await collectWarmupTickSample({ engineRoot, symbol });
    totalCollected += 1; // Each call that doesn't throw counts as attempted
  }

  // Clear the CSV mtime cache so the next health poll sees fresh data
  csvByteCache.clear();

  return {
    collected: totalCollected,
    errors: errors.length > 0 ? errors : [],
    duration_ms: Date.now() - startedAt,
  };
}

export async function warmPreparedCalls(): Promise<void> {
  // Mark the warmup attempt immediately so the ConnectionStatus never shows "Never"
  // while the system is alive, even if the warmup fails or is skipped.
  lastWarmupAt = new Date().toISOString();

  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return;
  }

  if (preparedCallWarmupTimer) {
    clearTimeout(preparedCallWarmupTimer);
    preparedCallWarmupTimer = null;
  }

  if (preparedCallWarmupPromise) {
    return preparedCallWarmupPromise;
  }

  preparedCallWarmupPromise = (async () => {
    if (manualCallGate) {
      await manualCallGate;
    }
    // ── Warmup live-tick strategy ─────────────────────────────────
    // Strategy: always use CSV-only mode (skipApi=true) for warmup calls.
    // The warmup is for background analysis of the cached CSV ticks — it
    // should complete quickly (< 15 seconds) and never hang on MT5.
    //
    // Previously, the warmup tried to collect 2 live ticks from MT5
    // (skipApi=false) when the terminal64 process was running. This caused
    // repeated 35-second timeouts when MT5 was unresponsive, blocking the
    // entire warmup cycle and preventing any analysis from completing.
    //
    // Live tick collection is now deferred to manual calls (user clicks
    // "Run" on a symbol), which connect to MT5 and append live ticks to
    // the CSV. The warmup then reads the updated CSV on its next cycle.
    //
    // The same-symbol warmups (sniper + active_trader) share a single
    // CSV read — no duplicate work.
    await Promise.all(
      PREPARED_CALL_WARMUP_SYMBOLS.flatMap((symbol) =>
        PREPARED_CALL_WARMUP_MODES.map(async (tradingMode) => {
        const cacheKey = `${symbol}_${tradingMode}`;
        try {
          // ── Check whether the CSV file has changed since last cycle ──
          // If the mtime is the same, skip the ~35s Python subprocess and
          // rely on the journal entry from the previous warmup (still fresh
          // enough for the prepared-call re-use check).
          const csvMtime = await getSymbolCsvMtime(engineRoot, symbol);
          const prev = warmupCsvTimestamps.get(cacheKey);
          if (prev !== undefined && csvMtime === prev.csvMtime) {
            // CSV unchanged AND the cache entry is still fresh (< 30s — TTL
            // enforced by createTtlCache's lazy eviction). Skip the analysis;
            // the previous journal entry is still valid for the prepared-call
            // re-use check. If the cache expired, get() returned undefined
            // so we re-run even if the CSV hasn't changed — the analysis may
            // reach a different conclusion as time passes (e.g., staleness
            // threshold).
            warmupCacheHits[symbol] = (warmupCacheHits[symbol] ?? 0) + 1;
            return;
          } else {
            warmupCacheMisses[symbol] = (warmupCacheMisses[symbol] ?? 0) + 1;
          }
          // ── Live tick collection strategy ─────────────────────────
          // Most warmup cycles (9 out of 10) use CSV-only mode (skipApi=true)
          // to keep the 45-second warmup fast and avoid unnecessary subprocess
          // timeouts. Every 10th cycle uses skipApi=false to collect fresh live
          // ticks via Deriv WebSocket (or MT5, if configured), keeping the CSV
          // velocity positive during idle periods.
          //
          // This ensures the HealthDashboard's tick velocity badge shows a
          // non-zero value even when the user hasn't clicked "Run" manually.
          const isLiveCycle = warmupCycleCounter % 2 === 0;
          const effectiveSkipApi = !isLiveCycle;
          const base = sanitizeUnavailableExecutionLevels(
            await readLiveSnapshotWithRetry({ engineRoot, symbol, mode: "prepared", skipApi: effectiveSkipApi, tradingMode }),
          );
          await appendHistoryEntry(
            applyAccountMode({
              base,
              accountMode: "own_account",
              propAccountState: null,
            }),
          );

          // ── Commit the mtime cache AFTER the analysis succeeds ──
          // Moving this after readLiveSnapshotWithRetry + appendHistoryEntry
          // ensures the cache is only updated on success. If the snapshot
          // fails (throws), the catch block swallows the error and the cache
          // is NOT updated — so the next warmup cycle will re-attempt.
          warmupCsvTimestamps.set(cacheKey, { csvMtime });
        } catch (warmupError) {
          // Warmup should never interrupt the manual call path.
          // On failure, clear the mtime cache so the next warmup cycle
          // re-attempts the live connection instead of being locked out.
          warmupCsvTimestamps.delete(cacheKey);
          // Surface the error in pipeline diagnostics so the UI shows
          // WHY the warmup failed instead of silently swallowing it.
          recordPipelineError(
            warmupError instanceof Error
              ? `[warmup] ${symbol}/${tradingMode}: ${warmupError.message.slice(0, 200)}`
              : `[warmup] ${symbol}/${tradingMode}: Unknown warmup failure`,
          );
        }
      })
      ));
    // ── Increment the warmup cycle counter ─────────────────────────
    // Placed AFTER the Promise.all so the counter advances exactly once
    // per warmup PASS, regardless of how many (symbol×mode) sub-calls
    // hit the CSV mtime cache. This is essential — if placed inside the
    // per-symbol loop, the counter would stall at 0 when all CSV files
    // are static, making EVERY cycle a live-tick cycle.
    warmupCycleCounter = (warmupCycleCounter + 1) % 1000;
  })().finally(() => {
    lastWarmupAt = new Date().toISOString();
    // Persist cache state to disk so warmup state survives hot reloads.
    void saveBridgeState();
    preparedCallWarmupPromise = null;
    if (!manualCallGate) {
      schedulePreparedCallWarmup(getPreparedCallWarmupRefreshMs());
    }
  });

  return preparedCallWarmupPromise;
}

function schedulePreparedCallWarmup(delayMs: number) {
  if (!getConfiguredEngineRoot() || preparedCallWarmupPromise || preparedCallWarmupTimer || manualCallGate) {
    return;
  }

  preparedCallWarmupTimer = setTimeout(() => {
    preparedCallWarmupTimer = null;
    void warmPreparedCalls();
  }, delayMs);
}

export function ensurePreparedCallWarmup() {
  // ── Immediate warmup on page load ─────────────────────────────────
  // When getSystemStatus() fires on page load, run the warmup IMMEDIATELY
  // instead of scheduling a 0-delay setTimeout. This populates pipeline
  // diagnostics within seconds instead of waiting for the 45-second timer.
  if (!getConfiguredEngineRoot()) return;
  if (preparedCallWarmupTimer) {
    clearTimeout(preparedCallWarmupTimer);
    preparedCallWarmupTimer = null;
  }
  // If a warmup is already in flight, skip — the in-flight warmup will
  // update pipeline diagnostics when it completes.
  if (!preparedCallWarmupPromise) {
    void warmPreparedCalls();
  }
}

export async function runFreshCall({
  symbol,
  accountMode,
  propAccountState,
  propConnection,
  reusePreparedCall = "eligible_only",
  tradingMode = "sniper",
  signal,
}: {
  symbol: SymbolCode;
  accountMode: AccountMode;
  propAccountState: PropAccountState | null;
  propConnection?: PropConnectionInput | null;
  reusePreparedCall?: PreparedCallReusePolicy;
  tradingMode?: TradingMode;
  signal?: AbortSignal;
}): Promise<FreshCallResponse> {
  void propConnection;

  // ── Fresh call cache (10s TTL) ──────────────────────────────
  // Reuse the last result when rapid polls arrive within the TTL
  // window. This prevents re-spawning a Python subprocess every
  // 10 seconds when both /api/calls/latest and /api/calls/guardian
  // hit the same symbol+mode.  Abort-signal callers (POST /run)
  // always bypass the cache to guarantee a fresh subprocess.
  const cacheKey = `${symbol}_${tradingMode}_${accountMode}`;
  if (!signal) {
    const cached = freshCallCache.get(cacheKey);
    if (cached) {
      return cached;
    }
  }

  const engineRoot = getConfiguredEngineRoot();
  let result: FreshCallResponse;

  if (!engineRoot) {
    result = buildUnavailableFreshCall({
      symbol,
      accountMode,
      propAccountState,
      detail: "The local engine path is not configured.",
    });
  } else {
    const prepared =
      reusePreparedCall === "never" ? null : await readPreparedCall(symbol);
    if (
      prepared &&
      prepared.symbol === symbol &&
      prepared.trading_mode === tradingMode
    ) {
      result = applyAccountMode({
        base: prepared,
        accountMode,
        propAccountState,
      });
    } else {
      // ── CSV-static fast path ─────────────────────────────────
      // When the CSV hasn't had any new ticks for 5+ seconds the
      // market is effectively idle.  Read the latest journal entry
      // directly (bypassing the age-based shouldReusePreparedCall)
      // and return it without launching a single subprocess.
      //
      // If CSV has changed OR no recent journal entry exists, fall
      // through to the normal subprocess path below.
      if (reusePreparedCall !== "never" && await isCsvStaticSinceMs(engineRoot, symbol, 5_000)) {
        const entries = await readHistoryEntries(symbol, 1);
        const latestEntry = entries[0];
        if (latestEntry && latestEntry.symbol === symbol && latestEntry.trading_mode === tradingMode) {
          result = applyAccountMode({
            base: refreshCallAge(toBaseFreshCall(latestEntry)),
            accountMode,
            propAccountState,
          });
          try { await appendHistoryEntry(result); } catch { /* best-effort */ }
          return result;
        }
      }

      // ── Warmup await with timeout ────────────────────────────
      // Never block a manual call on a stuck warmup subprocess.
      // If the warmup hasn't resolved within 5 seconds, proceed
      // without it — the warmup continues in the background and
      // its results will be available for the NEXT call.
      if (preparedCallWarmupPromise) {
        await Promise.race([
          preparedCallWarmupPromise,
          new Promise<void>((resolve) => setTimeout(resolve, 5_000)),
        ]);
      }
      let resolveManualGate: () => void = () => {};
      manualCallGate = new Promise<void>((resolve) => {
        resolveManualGate = resolve;
      });
      try {
        const raw = await readLiveSnapshotWithRetry({ engineRoot, symbol, tradingMode, signal });
        // ── Result quality check ──────────────────────────────
        // The Python subprocess can succeed (HTTP 200) but return
        // unusable stale data (guardian_state: "unavailable"). In
        // that case the catch block is never reached, so we check
        // the result explicitly and fall back to buildFallbackFreshCall.
        if (raw.guardian_state === "unavailable") {
          result = await buildFallbackFreshCall({
            symbol,
            tradingMode,
            accountMode,
            propAccountState,
            detail: "Live data is stale — using cached analysis.",
          });
        } else {
          const base = sanitizeUnavailableExecutionLevels(raw);
          result = applyAccountMode({
            base,
            accountMode,
            propAccountState,
          });
        }
      } catch (error: unknown) {
        if (error instanceof DOMException && error.name === "AbortError") {
          throw error;
        }
        if (signal?.aborted) {
          throw new DOMException("Canceled", "AbortError");
        }
        result = await buildFallbackFreshCall({
          symbol,
          tradingMode,
          accountMode,
          propAccountState,
          detail: "Live bridge unavailable — using cached analysis.",
        });
      } finally {
        resolveManualGate();
        manualCallGate = null;
        schedulePreparedCallWarmup(0);
      }
    }
  }

  try {
    await appendHistoryEntry(result);
  } catch {
    // History should not break the live call path.
  }

  // ── Cache store / invalidation ──────────────────────────────
  // Non-signal callers (GET /latest, GET /guardian) store the result
  // so rapid polls reuse it within the 10s TTL window.
  // Signal callers (POST /run) invalidate the stale entry so the
  // next poll spawns a fresh subprocess instead of returning old data.
  if (!signal) {
    freshCallCache.set(cacheKey, result);
  } else {
    freshCallCache.delete(cacheKey);
  }

  return result;
}

export async function getLatestCall(
  symbol: SymbolCode,
  tradingMode: TradingMode = "sniper",
) {
  // Always run a fresh Python subprocess — never return stale journal data.
  // The CSV-static fast path (reusePreparedCall: "eligible_only") returns
  // the latest journal entry when the CSV hasn't changed for 5+ seconds,
  // but that entry can be a stale "forming" result from an earlier state.
  // The Refresh button already uses "never" and always works correctly.
  return runFreshCall({
    symbol,
    accountMode: "own_account",
    propAccountState: null,
    tradingMode,
    reusePreparedCall: "never",
  });
}

export async function getGuardianStatus(
  symbol: SymbolCode,
  tradingMode: TradingMode = "sniper",
): Promise<GuardianStatus> {
  const call = await runFreshCall({
    symbol,
    accountMode: "own_account",
    propAccountState: null,
    tradingMode,
  });

  return guardianStatusSchema.parse({
    symbol: call.symbol,
    guardian_state: call.guardian_state,
    guardian_reason: call.guardian_reason,
    current_close: call.current_close,
    generated_at: call.generated_at,
  });
}

export async function getRecentHistory(symbol: SymbolCode) {
  const history = await readHistoryEntries(symbol);

  return {
    history,
  };
}

export async function getSystemStatus() {
  const engineRoot = getConfiguredEngineRoot();
  const mt5Config = getConfiguredLivePropProfile();

  if (engineRoot) {
    ensurePreparedCallWarmup();

    // Parallel health reads — all independent, no ordering dependency.
    let mt5Running = false;
    let mt5LastError: string | null = null;
    let mt5LastConnectedAtValue: string | null = mt5LastConnectedAt;
    let mt5LastTest: Mt5TestFileRecord | null = null;
    let engineVersion: string | null = null;
    let csvTicks: Record<string, number> = { R_75: 0, R_100: 0 };

    const tasks: Promise<unknown>[] = [
      countCsvTicks(engineRoot).then((r) => { csvTicks = r; }),
      readEngineVersion(engineRoot).then((r) => { engineVersion = r; }),
      readMt5LastError(engineRoot).then((r) => { mt5LastError = r; }),
      readMt5LastTest(engineRoot).then((r) => { mt5LastTest = r; }),
    ];
    if (mt5Config) {
      tasks.push(
        isMt5ProcessRunning().then((r) => { mt5Running = r; }),
      );
    }
    await Promise.all(tasks);

    return {
      latest_call: "Bridge running",
      alert_count: 0,
      suppressed_context_count: 0,
      transport_event_count: 0,
      latest_transport_event: "live_bridge_ready",
      latest_transport_reason: "The live engine bridge is connected and operational.",
      backend_status: "live_bridge_ready",
      journal_status: "active",
      // ── MT5 connection health ──────────────────────────────
      mt5_configured: mt5Config !== null,
      mt5_process_running: mt5Running,
      mt5_last_error: mt5LastError,
      mt5_last_connected_at: mt5LastConnectedAtValue,
      mt5_last_test: mt5LastTest,
      mt5_server: process.env.SYNTHETIC_MT5_SERVER?.trim() ?? null,
      engine_version: engineVersion,
      csv_ticks: csvTicks,
    };
  }

  return {
    latest_call: "No live decision loaded",
    alert_count: 0,
    suppressed_context_count: 0,
    transport_event_count: 0,
    latest_transport_event: "engine_not_configured",
    latest_transport_reason: "The local engine path is not configured.",
    backend_status: "engine_not_configured",
    journal_status: "inactive",
    mt5_configured: mt5Config !== null,
    mt5_process_running: false,
    mt5_last_error: null,
    mt5_last_connected_at: null,
    mt5_last_test: null,
    mt5_server: process.env.SYNTHETIC_MT5_SERVER?.trim() ?? null,
    engine_version: null,
    csv_ticks: { R_75: 0, R_100: 0 },
  };
}

/**
 * Run a single Python subprocess that imports every synthetic_trader
 * submodule and reports any ImportError or SyntaxError. This lets the
 * frontend diagnose engine health (missing dependencies, broken imports)
 * without digging through server logs.
 *
 * Returns a summary with total module count, count of failures, and a
 * list of per-module error details.
 */
export async function validateEngineModules(): Promise<{
  counted: number;
  failed: number;
  modules: Array<{ module: string; status: "ok" | "fail"; error?: string; traceback?: string }>;
  engine_root: string | null;
  python_version: string | null;
}> {
  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return { counted: 0, failed: 0, modules: [], engine_root: null, python_version: null };
  }

  const pythonScript = `
import json
import sys
import traceback
import pkgutil
import importlib

def try_import(name: str) -> dict:
    try:
        importlib.import_module(name)
        return {"module": name, "status": "ok"}
    except Exception as e:
        tb = traceback.format_exc()
        # Truncate traceback â€” the first 800 chars is enough to identify the error
        if len(tb) > 800:
            tb = tb[:800] + "... (truncated)"
        return {"module": name, "status": "fail", "error": str(e), "traceback": tb}

# Collect all reachable module names under synthetic_trader
modules: list[dict] = []
visited: set[str] = set()
queue: list[str] = ["synthetic_trader"]

while queue:
    name = queue.pop(0)
    if name in visited:
        continue
    visited.add(name)
    result = try_import(name)
    modules.append(result)
    if result["status"] == "ok":
        try:
            mod = importlib.import_module(name)
            if hasattr(mod, "__path__"):
                for importer, pkg_name, is_pkg in pkgutil.walk_packages(
                    mod.__path__, prefix=name + "."
                ):
                    if pkg_name not in visited:
                        queue.append(pkg_name)
        except Exception:
            pass

# Get Python version
py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

print(json.dumps({
    "counted": len(modules),
    "failed": sum(1 for m in modules if m["status"] == "fail"),
    "modules": modules,
    "python_version": py_version,
}))
`.trim();

  try {
    const { stdout } = await runPythonScript({
      engineRoot,
      pythonScript,
      timeout: 20000,
      label: "validateEngineModules",
    });
    const parsed = JSON.parse(stdout.trim()) as {
      counted: number;
      failed: number;
      modules: Array<{ module: string; status: "ok" | "fail"; error?: string; traceback?: string }>;
      python_version: string;
    };
    return {
      ...parsed,
      engine_root: engineRoot,
    };
  } catch (error) {
    // runPythonScript already logs stderr via recordPipelineStderr
    return {
      counted: 0,
      failed: 1,
      modules: [{ module: "synthetic_trader", status: "fail", error: "Unable to run Python subprocess", traceback: error instanceof Error ? error.message : String(error) }],
      engine_root: engineRoot,
      python_version: null,
    };
  }
}

function buildUnavailablePropProfile(): PropProfileResponse {
  return {
    profile: "blueberry_2step_funded",
    startingBalance: 5000,
    currentBalance: 5000,
    currentEquity: 5000,
    todaysRealizedLoss: 0,
    todaysFloatingLossExposure: 0,
    highImpactNewsLockout: false,
    telemetry: {
      status: "live_unavailable",
      message: "MT5 not configured or unreachable — no prop profile available",
    },
  };
}

export async function getCurrentPropProfile() {
  const engineRoot = getConfiguredEngineRoot();
  const liveConfig = getConfiguredLivePropProfile();

  if (!engineRoot || !liveConfig) {
    return buildUnavailablePropProfile();
  }

  try {
    const profile = await livePropProfileAdapter.read({
      engineRoot,
      config: liveConfig,
    });

    return withTelemetry(profile, {
      status: "own_account_fallback",
      message: "Using own-account fallback",
    });
  } catch {
    return buildUnavailablePropProfile();
  }
}

export async function getCurrentPropProfileForRequest(
  request: PropProfileRequest | null | undefined,
) {
  const engineRoot = getConfiguredEngineRoot();
  const liveConfig = resolveRequestedPropConfig(request);
  const usedFallback =
    !request?.connection?.server &&
    !request?.connection?.login &&
    !request?.connection?.password;

  if (!engineRoot || !liveConfig) {
    return buildUnavailablePropProfile();
  }

  try {
    const profile = await livePropProfileAdapter.read({
      engineRoot,
      config: liveConfig,
    });

    return withTelemetry(
      profile,
      usedFallback
        ? {
            status: "own_account_fallback",
            message: "Using own-account fallback",
          }
        : {
            status: "live_confirmed",
            message: "Live prop check confirmed",
          },
    );
  } catch {
    return buildUnavailablePropProfile();
  }
}

async function executePythonOrder({
  engineRoot,
  direction,
  entry,
  stopLoss,
  takeProfit,
  executionMode,
  mt5Volume,
  symbol,
}: {
  engineRoot: string;
  direction: "buy" | "sell";
  entry: number;
  stopLoss: number;
  takeProfit: number;
  executionMode: ExecutionMode;
  mt5Volume?: number;
  symbol: string;
}): Promise<SubmitOrderResponse> {
  if (executionMode === "paper") {
    const paperPositionId = `paper_${symbol.toLowerCase()}_${direction}`;
    const pythonScript = `
import json
from synthetic_trader.domain import Candle, Direction, OrderIntent, TradeSignal
from synthetic_trader.execution.paper import PaperBroker

try:
    broker = PaperBroker()
    candle = Candle(epoch=0, open=${entry}, high=${entry}, low=${entry}, close=${entry}, volume=0)

    intent = OrderIntent(
        signal=TradeSignal(
            symbol="${symbol}",
            direction=Direction.${direction === "buy" ? "LONG" : "SHORT"},
            confidence=0.6,
            min_confidence=0.5,
            entry=${entry},
            stop_loss=${stopLoss},
            take_profit=${takeProfit},
            horizon_sec=3600,
        ),
        stake=100.0,
        max_loss=100.0,
    )
    outcome = broker.submit(intent, candle)
    result = {
        "accepted": True,
        "position_id": "${paperPositionId}",
        "entry_price": ${entry},
        "stop_loss": ${stopLoss},
        "take_profit": ${takeProfit},
        "message": "Paper order executed.",
    }
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({
        "accepted": False,
        "position_id": None,
        "entry_price": None,
        "stop_loss": None,
        "take_profit": None,
        "message": f"Paper order error: {e}",
    }))
`.trim();

    const { stdout } = await withImportCheck(engineRoot,
      () => runPythonScript({
        engineRoot,
        pythonScript,
        timeout: 30000,
        label: "submitOrder (paper)",
      }),
      "executePythonOrder (paper)",
    );
    return submitOrderResponseSchema.parse(JSON.parse(stdout.trim()));
  }

  const configuredServer = process.env.SYNTHETIC_MT5_SERVER?.trim() ?? "";
  const configuredLogin = process.env.SYNTHETIC_MT5_LOGIN?.trim() ?? "";
  const configuredPassword = process.env.SYNTHETIC_MT5_PASSWORD?.trim() ?? "";
  const configuredTerminal = process.env.SYNTHETIC_MT5_TERMINAL_PATH?.trim() ?? "";
  // Blueberry Markets uses 'Blueberry Volatility X' — try multiple names for compatibility
  const volNum = symbol === "R_75" ? "75" : "100";
  const mt5SymbolCandidates = [
    `Blueberry Volatility ${volNum}`,
    `Volatility ${volNum} Index`,
    `Volatility ${volNum}`,
    `Vol ${volNum} Index`,
    `Vol ${volNum}`,
    `R_${volNum}`,
  ];
  const volume = mt5Volume ?? 0.01;

  const pythonScript = `
import json
import MetaTrader5 as mt5
${MT5_CTX}

try:
    with _mt5(tp=${JSON.stringify(configuredTerminal || null)},lg=${configuredLogin},pw=${JSON.stringify(configuredPassword)},sv=${JSON.stringify(configuredServer)}):
        # Resolve MT5 symbol — try Blueberry Markets name first, then fallbacks
        _candidates = ${JSON.stringify(mt5SymbolCandidates)}
        mt5_symbol = None
        for _name in _candidates:
            if mt5.symbol_info(_name) is not None:
                mt5_symbol = _name
                break
        if mt5_symbol is None:
            print(json.dumps({"accepted": False, "position_id": None, "entry_price": None, "stop_loss": None, "take_profit": None, "message": f"Symbol not found. Tried: {', '.join(_candidates)}"}))
            raise SystemExit(0)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": mt5_symbol,
            "volume": ${volume},
            "type": mt5.ORDER_TYPE_${direction === "buy" ? "BUY" : "SELL"},
            "price": ${entry},
            "sl": ${stopLoss},
            "tp": ${takeProfit},
            "deviation": 20,
            "magic": 123456,
            "comment": "synthetic-trader",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }

        result = mt5.order_send(request)
        if result is None:
            print(json.dumps({"accepted": False, "position_id": None, "entry_price": None, "stop_loss": None, "take_profit": None, "message": "Order send returned None"}))
        elif result.retcode == mt5.TRADE_RETCODE_DONE:
            print(json.dumps({"accepted": True, "position_id": str(result.order), "entry_price": result.price, "stop_loss": ${stopLoss}, "take_profit": ${takeProfit}, "message": f"MT5 order placed. Ticket: {result.order}"}))
        else:
            print(json.dumps({"accepted": False, "position_id": None, "entry_price": None, "stop_loss": None, "take_profit": None, "message": f"MT5 order failed. Retcode: {result.retcode}, Comment: {result.comment}"}))
except RuntimeError as e:
    print(json.dumps({"accepted": False, "position_id": None, "entry_price": None, "stop_loss": None, "take_profit": None, "message": f"{e}"}))
except Exception as e:
    print(json.dumps({"accepted": False, "position_id": None, "entry_price": None, "stop_loss": None, "take_profit": None, "message": f"MT5 order error: {e}"}))
`.trim();

  const { stdout } = await withImportCheck(engineRoot,
    () => runPythonScript({
      engineRoot,
      pythonScript,
      timeout: 30000,
      label: "submitOrder (MT5)",
    }),
    "executePythonOrder (MT5)",
  );
  return submitOrderResponseSchema.parse(JSON.parse(stdout.trim()));
}

export async function submitOrder({
  symbol,
  direction,
  entry,
  stopLoss,
  takeProfit,
  executionStop,
  primaryTarget,
  extendedTarget,
  executionMode,
  mt5Volume,
}: {
  symbol: "R_75" | "R_100";
  direction: "buy" | "sell";
  entry: number;
  stopLoss: number;
  takeProfit: number;
  executionStop?: number | null;
  primaryTarget?: number | null;
  extendedTarget?: number | null;
  executionMode: ExecutionMode;
  mt5Volume?: number;
}): Promise<SubmitOrderResponse> {
  void executionStop; void primaryTarget; void extendedTarget;

  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return {
      accepted: false,
      position_id: null,
      entry_price: null,
      stop_loss: null,
      take_profit: null,
      message: "Engine not configured.",
    };
  }

  // executePythonOrder uses runPythonScript() internally which handles
  // candidate iteration (SYNTHETIC_ENGINE_PYTHON → python → py -3).
  return await executePythonOrder({
    engineRoot,
    direction,
    entry,
    stopLoss,
    takeProfit,
    executionMode,
    mt5Volume,
    symbol,
  });
}

export async function closePosition({
  executionMode,
  mt5Ticket,
}: {
  executionMode: ExecutionMode;
  mt5Ticket?: number | null;
}): Promise<{ closed: boolean; message: string }> {
  if (executionMode === "paper") {
    return { closed: true, message: "Paper position closed." };
  }

  if (!mt5Ticket) {
    return { closed: false, message: "No MT5 ticket provided." };
  }

  const engineRoot = getConfiguredEngineRoot();
  if (!engineRoot) {
    return { closed: false, message: "Engine not configured." };
  }

  const configuredServer = process.env.SYNTHETIC_MT5_SERVER?.trim() ?? "";
    const configuredLogin = process.env.SYNTHETIC_MT5_LOGIN?.trim() ?? "";
    const configuredPassword = process.env.SYNTHETIC_MT5_PASSWORD?.trim() ?? "";
    const configuredTerminal = process.env.SYNTHETIC_MT5_TERMINAL_PATH?.trim() || resolveTerminalPath() || "";

    const pythonScript = `
import json
import MetaTrader5 as mt5
${MT5_CTX}

try:
    with _mt5(tp=${JSON.stringify(configuredTerminal || null)},lg=${configuredLogin},pw=${JSON.stringify(configuredPassword)},sv=${JSON.stringify(configuredServer)}):
        positions = mt5.positions_get(ticket=${mt5Ticket})
        if not positions:
            print(json.dumps({"closed": False, "message": "Position not found."}))
            raise SystemExit(0)

        pos = positions[0]
        close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": pos.ticket,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "price": mt5.symbol_info_tick(pos.symbol).bid if close_type == mt5.ORDER_TYPE_SELL else mt5.symbol_info_tick(pos.symbol).ask,
            "deviation": 20,
            "magic": 123456,
            "comment": "synthetic-trader-close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }

        result = mt5.order_send(request)
        if result is None:
            print(json.dumps({"closed": False, "message": "Close order returned None."}))
        elif result.retcode == mt5.TRADE_RETCODE_DONE:
            print(json.dumps({"closed": True, "message": f"Position closed. Ticket: {pos.ticket}"}))
        else:
            print(json.dumps({"closed": False, "message": f"Close failed. Retcode: {result.retcode}"}))
except RuntimeError as e:
    print(json.dumps({"closed": False, "message": f"{e}"}))
except Exception as e:
    print(json.dumps({"closed": False, "message": f"Close position error: {e}"}))
`.trim();

  try {
    const { stdout } = await runPythonScript({
      engineRoot,
      pythonScript,
      timeout: 30000,
      label: "closePosition",
    });
    return closePositionResponseSchema.parse(JSON.parse(stdout.trim()));
    } catch {
      // runPythonScript already logs stderr via recordPipelineStderr
      return { closed: false, message: "Failed to close position." };
  }
}
