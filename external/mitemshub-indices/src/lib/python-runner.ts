/**
 * python-runner.ts — Centralized Python subprocess execution for the engine bridge.
 *
 * Every Python subprocess spawned by the engine goes through `runPythonScript`,
 * which handles stdout parsing, stderr logging, timeout, environment building,
 * timing, candidate iteration (python → py -3), import validation, and signal
 * cancellation.
 *
 * Extracted from engine-bridge.ts so the runner is independently testable and
 * reusable across the codebase.
 */

import { execFile } from "node:child_process";
import { join } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

// ── Python child process environment ────────────────────────────
// Only explicitly allowed env vars and MT5-specific vars are forwarded
// to the subprocess. Arbitrary process.env values are NOT leaked.

function buildPythonChildEnv(extra: Record<string, string> = {}): NodeJS.ProcessEnv {
  const allowed = [
    "PATH", "SystemRoot", "TEMP", "TMP", "USERPROFILE", "HOME",
    "APPDATA", "LOCALAPPDATA",
    "PATHEXT", "COMSPEC",
    "PYTHONDONTWRITEBYTECODE",
  ];
  const safe: Record<string, string> = Object.create(null);
  for (const key of allowed) {
    const val = process.env[key];
    if (val !== undefined) safe[key] = val;
  }
  safe.NODE_ENV = process.env.NODE_ENV || "production";
  const result = { ...safe, ...extra } as Record<string, string>;
  const mt5Vars = [
    "SYNTHETIC_MT5_SERVER", "SYNTHETIC_MT5_LOGIN", "SYNTHETIC_MT5_PASSWORD",
    "SYNTHETIC_MT5_TERMINAL_PATH", "SYNTHETIC_MT5_SYMBOL_MAP",
    "DERIV_APP_ID", "DERIV_API_TOKEN",
  ];
  for (const key of mt5Vars) {
    const val = process.env[key];
    if (val !== undefined) result[key] = val;
  }
  return result as NodeJS.ProcessEnv;
}

// ── Types ──────────────────────────────────────────────────────

export type RunPythonScriptOptions = {
  engineRoot: string;
  pythonScript: string;
  timeout: number;
  signal?: AbortSignal;
  label?: string;
  extraEnv?: Record<string, string>;
  /**
   * If set, run a quick import smoke test before the main script.
   * The value should be a Python import statement such as
   * `"from synthetic_trader.live.market_snapshot import build_watch_alert"`.
   * Uses the same 60-second TTL cache as `checkPythonImport`.
   */
  validatePythonImport?: string;
};

export type RunPythonScriptResult = {
  stdout: string;
  stderr: string;
  durationMs: number;
};

// ── Pipeline diagnostics store ─────────────────────────────────
// Shared mutable state recording the most recent failure diagnostics
// (Python stderr, retry count, guardian reason, errors). Written by
// the runner and read by the health/metrics endpoints.

type PipelineDiagnostics = {
  lastGuardianReason: string | null;
  lastStderr: string | null;
  lastRetryCount: number;
  lastError: string | null;
  lastUpdatedAt: string | null;
  staleDataSince: number | null;
};

const pipelineDiagnostics: PipelineDiagnostics = {
  lastGuardianReason: null,
  lastStderr: null,
  lastRetryCount: 0,
  lastError: null,
  lastUpdatedAt: null,
  staleDataSince: null,
};

export function recordPipelineGuardianReason(reason: string | null | undefined): void {
  if (reason && reason.trim()) {
    pipelineDiagnostics.lastGuardianReason = reason;
    pipelineDiagnostics.lastUpdatedAt = new Date().toISOString();
  }
}

export function recordPipelineStderr(stderr: string | null | undefined): void {
  if (stderr && stderr.trim()) {
    pipelineDiagnostics.lastStderr = stderr;
    pipelineDiagnostics.lastUpdatedAt = new Date().toISOString();
  }
}

export function recordPipelineRetry(attempt: number): void {
  pipelineDiagnostics.lastRetryCount = attempt;
  pipelineDiagnostics.lastUpdatedAt = new Date().toISOString();
}

export function recordPipelineError(error: string | null | undefined): void {
  if (error && error.trim()) {
    pipelineDiagnostics.lastError = error;
    pipelineDiagnostics.lastUpdatedAt = new Date().toISOString();
  }
}

export function recordPipelineStaleDataSince(epoch: number | null | undefined): void {
  if (typeof epoch === "number" && Number.isFinite(epoch)) {
    pipelineDiagnostics.staleDataSince = epoch;
    pipelineDiagnostics.lastUpdatedAt = new Date().toISOString();
  }
}

export function getPipelineDiagnostics() {
  return { ...pipelineDiagnostics } as PipelineDiagnostics;
}

// ── TTL cache factory ─────────────────────────────────────────
// A generic TTL cache used by both the import check and warmup
// CSV caches. Entries expire `ttlMs` ms after `set()` and are
// lazily evicted on `get()`. A `setWithTimestamp()` variant
// allows restoring persisted entries (e.g., after server restart
// from bridge_state.json).

type TtlCacheEntry<T> = { value: T; storedAt: number };

export type TtlCache<T> = {
  /** Returns the value if present and not expired, otherwise undefined. */
  get(key: string): T | undefined;
  /** Store a value stamped with the current time. */
  set(key: string, value: T): void;
  /** Store a value with an explicit timestamp (for deserialization). */
  setWithTimestamp(key: string, value: T, storedAt: number): void;
  /** Remove a single entry. */
  delete(key: string): void;
  /** Remove all entries. */
  clear(): void;
  /** All non-expired entries with their stored-at timestamps (for serialization). */
  entries(): IterableIterator<[string, TtlCacheEntry<T>]>;
};

export function createTtlCache<T>(ttlMs: number): TtlCache<T> {
  const store = new Map<string, TtlCacheEntry<T>>();

  function isExpired(storedAt: number): boolean {
    return Date.now() - storedAt >= ttlMs;
  }

  return {
    get(key: string): T | undefined {
      const entry = store.get(key);
      if (!entry) return undefined;
      if (isExpired(entry.storedAt)) {
        store.delete(key);
        return undefined;
      }
      return entry.value;
    },

    set(key: string, value: T): void {
      store.set(key, { value, storedAt: Date.now() });
    },

    setWithTimestamp(key: string, value: T, storedAt: number): void {
      store.set(key, { value, storedAt });
    },

    delete(key: string): void {
      store.delete(key);
    },

    clear(): void {
      store.clear();
    },

    entries(): IterableIterator<[string, TtlCacheEntry<T>]> {
      return store.entries();
    },
  };
}

// ── Python import cache (60s TTL) ──────────────────────────────
// Repeated calls to checkPythonImport within a warmup cycle would
// each spawn a separate subprocess. The cache avoids this.

const checkImportCache = createTtlCache<{ ok: boolean }>(60_000);

/**
 * Quick import-time smoke test for a Python module.
 *
 * Runs `python -c "<importStmt>; print('OK')"` before attempting the main
 * subprocess, so import errors (missing dependencies, syntax errors, broken
 * PYTHONPATH) are caught early instead of wasting the caller's timeout.
 *
 * Returns `true` on success, `false` on failure. Results are cached with a
 * 60-second TTL per import statement per engine root.
 */
export async function checkPythonImport(engineRoot: string, importModule?: string): Promise<boolean> {
  const cacheKey = importModule ? `${engineRoot}::import::${importModule}` : engineRoot;
  const cached = checkImportCache.get(cacheKey);
  if (cached !== undefined) {
    return cached.ok;
  }

  const importStmt = importModule ?? "from synthetic_trader.live.market_snapshot import build_watch_alert";
  try {
    const { stdout } = await runPythonScript({
      engineRoot,
      pythonScript: `${importStmt}; print('OK')`,
      timeout: 8000,
      label: importModule ? `checkImport:${importModule.slice(0, 80)}` : "checkPythonImport",
    });
    const ok = stdout.trim() === "OK";
    checkImportCache.set(cacheKey, { ok });
    return ok;
  } catch {
    checkImportCache.set(cacheKey, { ok: false });
    return false;
  }
}

/** Test-only helper: clear the import cache so the next call re-checks. */
export function __testResetImportCache(): void {
  checkImportCache.clear();
}

/**
 * Wraps a Python-dependent operation with an import smoke test.
 *
 * Runs `checkPythonImport(engineRoot)` first; if it fails, throws
 * an Error with a descriptive message. Otherwise executes `fn`.
 * The import result is cached with a 60-second TTL, so repeated
 * calls (e.g., wrapping each `runPythonScript` call individually)
 * only spawn one subprocess per cache window — no performance
 * penalty for being thorough.
 *
 * Usage:
 *   return await withImportCheck(engineRoot,
 *     () => runPythonScript({ engineRoot, pythonScript, ... }),
 *     "readLiveSnapshot",
 *   );
 */
export async function withImportCheck<T>(
  engineRoot: string,
  fn: () => Promise<T>,
  label?: string,
): Promise<T> {
  const importOk = await checkPythonImport(engineRoot);
  if (!importOk) {
    throw new Error(
      `[withImportCheck${label ? `:${label}` : ""}] Python import validation failed`,
    );
  }
  return await fn();
}

// ── Core runner ────────────────────────────────────────────────

/**
 * Run a Python script as a child process, with candidate fallback
 * (python → py -3), safe environment building, stderr capture,
 * timeout, signal cancellation, and optional pre-flight import
 * validation.
 */
export async function runPythonScript(options: RunPythonScriptOptions): Promise<RunPythonScriptResult> {
  // Pre-flight import validation — catches broken PYTHONPATH or missing
  // modules before the main subprocess runs.
  if (options.validatePythonImport) {
    const importOk = await checkPythonImport(options.engineRoot, options.validatePythonImport);
    if (!importOk) {
      throw new Error(
        `[python-runner] ${options.label ?? "python"}: import validation failed — "${options.validatePythonImport}"`,
      );
    }
  }

  const configuredPython = process.env.SYNTHETIC_ENGINE_PYTHON?.trim();
  const candidates = configuredPython
    ? [{ command: configuredPython, args: [] as string[] }]
    : [
        { command: "python", args: [] as string[] },
        { command: "py", args: ["-3"] as string[] },
      ];

  const label = options.label ?? "python";
  const pythonPath = join(options.engineRoot, "src");
  let lastError: unknown;

  for (const { command, args } of candidates) {
    const startedAt = Date.now();
    try {
      const result = await execFileAsync(
        command,
        [...args, "-c", options.pythonScript],
        {
          cwd: options.engineRoot,
          env: buildPythonChildEnv({
            PYTHONPATH: pythonPath,
            PYTHONDONTWRITEBYTECODE: "1",
            ...options.extraEnv,
          }),
          timeout: options.timeout,
          windowsHide: true,
          signal: options.signal,
        },
      );

      if (result.stderr?.trim()) {
        console.error(`[python-runner] ${label} stderr:`, result.stderr);
        recordPipelineStderr(result.stderr);
      }

      return {
        stdout: result.stdout,
        stderr: result.stderr,
        durationMs: Date.now() - startedAt,
      };
    } catch (error) {
      const execError = error as { stderr?: string };
      if (execError?.stderr) {
        console.error(`[python-runner] ${label} stderr:`, execError.stderr);
      }
      lastError = error;
    }
  }

  throw lastError instanceof Error
    ? lastError
    : new Error("Unable to run Python subprocess");
}

/** @private Test helper — exposes the private runPythonScript for unit testing. */
export async function __testRunPythonScript(
  options: RunPythonScriptOptions,
): Promise<RunPythonScriptResult> {
  return runPythonScript(options);
}

/** Re-export execFileAsync for engine-bridge.ts (used by _realIsMt5ProcessRunning). */
export { execFileAsync };
