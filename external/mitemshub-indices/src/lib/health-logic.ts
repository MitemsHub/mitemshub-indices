/**
 * Pure health-evaluation logic extracted from the HealthDashboard component
 * so it can be unit-tested without React infrastructure.
 */

// ── localStorage key ─────────────────────────────────────────────

export const THRESHOLD_STORE_KEY = "mitems_health_thresholds";

// ── Thresholds type ──────────────────────────────────────────────

export type AlertThresholds = {
  /** MT5 initialize time (ms) above which the health badge turns amber/red. */
  mt5InitWarnMs: number;
  mt5InitCritMs: number;

  /** CSV tick velocity (ticks/min) below which ingestion is flagged. */
  csvVelocityWarnTicksMin: number;
  csvVelocityCritTicksMin: number;

  /** Consecutive polls with zero tick-count change before flagging. */
  flatTicksWarnPolls: number;
  flatTicksCritPolls: number;

  /** Poll interval (ms) — used to estimate how many ticks to expect. */
  pollIntervalMs: number;
};

// ── Default thresholds ────────────────────────────────────────────

export const DEFAULT_THRESHOLDS: AlertThresholds = {
  mt5InitWarnMs: 15_000,
  mt5InitCritMs: 30_000,
  csvVelocityWarnTicksMin: 50,
  csvVelocityCritTicksMin: 10,
  flatTicksWarnPolls: 8,
  flatTicksCritPolls: 16,
  pollIntervalMs: 15_000,
};

// ── Types ─────────────────────────────────────────────────────────

export type HealthStatus = "green" | "amber" | "red" | "offline";

export type HealthAlert = {
  type: "mt5_latency" | "csv_velocity" | "ticks_stalled";
  severity: "warn" | "crit";
  message: string;
};

export type Mt5Timing = {
  init_ms: number;
  login_ms: number;
  total_ms: number;
  timestamp: number;
};

export type Mt5TestResult = {
  success: boolean;
  error: string | null;
  server: string | null;
  terminal_path: string | null;
  duration_ms: number;
  account_name: string | null;
  account_balance: number | null;
  tested_at: string;
};

export type HealthMetrics = {
  mt5_configured: boolean;
  mt5_server: string | null;
  mt5_error: string | null;
  mt5_timing: Mt5Timing | null;
  /** Whether the MT5 terminal64.exe process is currently running. */
  mt5_process_running: boolean;
  /** ISO timestamp of the last successful MT5 initialize+login. */
  mt5_last_connected_at: string | null;
  /** Result of the most recent MT5 test connection attempt. */
  mt5_last_test: Mt5TestResult | null;
  csv_size_bytes: number;
  csv_ticks: Record<string, number>;
  health_history: Array<{
    timestamp: number;
    mt5_init_ms: number;
    mt5_login_ms: number;
    mt5_total_ms: number;
    csv_ticks: Record<string, number>;
  }>;
  snapshot_phases: Record<string, unknown> | null;
  engine_version: string | null;
  timestamp: number;
  warmup_cache_hits: Record<string, number>;
  warmup_cache_misses: Record<string, number>;
  csv_cache_hit_ratio: number;
  last_warmup_at: string | null;
  /** Set to true when the Python subprocesses consistently time out or fail,
   *  indicating the bridge between the Next.js server and the Python engine
   *  is unreachable. When true, the HealthDashboard shows "Bridge Offline"
   *  instead of "Critical" — a more accurate description of the root cause. */
  bridge_unavailable: boolean;
  pipeline_diagnostics: {
    lastGuardianReason: string | null;
    lastStderr: string | null;
    lastRetryCount: number;
    lastError: string | null;
    lastUpdatedAt: string | null;
    staleDataSince: number | null;
  };
};

// ── Standard field metadata for the inline editor ────────────────

export type ThresholdField = {
  key: keyof AlertThresholds;
  label: string;
  hint: string;
  min: number;
  step: number;
  suffix: string;
};

export const THRESHOLD_FIELDS: ThresholdField[] = [
  { key: "mt5InitWarnMs", label: "MT5 Init Warn", hint: "ms above which badge turns amber", min: 100, step: 100, suffix: "ms" },
  { key: "mt5InitCritMs", label: "MT5 Init Crit", hint: "ms above which badge turns red", min: 100, step: 100, suffix: "ms" },
  { key: "csvVelocityWarnTicksMin", label: "Velocity Warn", hint: "ticks/min below which ingestion flags", min: 1, step: 1, suffix: "/min" },
  { key: "csvVelocityCritTicksMin", label: "Velocity Crit", hint: "ticks/min below which is critical", min: 1, step: 1, suffix: "/min" },
  { key: "flatTicksWarnPolls", label: "Flat Warn", hint: "consecutive polls without change", min: 1, step: 1, suffix: "polls" },
  { key: "flatTicksCritPolls", label: "Flat Crit", hint: "consecutive polls → stalled", min: 1, step: 1, suffix: "polls" },
  { key: "pollIntervalMs", label: "Poll Interval", hint: "ms between health checks", min: 1000, step: 500, suffix: "ms" },
];

// ── Persistence helpers ───────────────────────────────────────────

/** Load custom thresholds from localStorage, falling back to defaults. */
export function loadThresholds(): AlertThresholds {
  try {
    const raw = localStorage.getItem(THRESHOLD_STORE_KEY);
    if (!raw) return { ...DEFAULT_THRESHOLDS };
    const parsed = JSON.parse(raw) as Partial<AlertThresholds>;
    // Merge with defaults so missing keys don't cause NaN
    return {
      mt5InitWarnMs: parsed.mt5InitWarnMs ?? DEFAULT_THRESHOLDS.mt5InitWarnMs,
      mt5InitCritMs: parsed.mt5InitCritMs ?? DEFAULT_THRESHOLDS.mt5InitCritMs,
      csvVelocityWarnTicksMin: parsed.csvVelocityWarnTicksMin ?? DEFAULT_THRESHOLDS.csvVelocityWarnTicksMin,
      csvVelocityCritTicksMin: parsed.csvVelocityCritTicksMin ?? DEFAULT_THRESHOLDS.csvVelocityCritTicksMin,
      flatTicksWarnPolls: parsed.flatTicksWarnPolls ?? DEFAULT_THRESHOLDS.flatTicksWarnPolls,
      flatTicksCritPolls: parsed.flatTicksCritPolls ?? DEFAULT_THRESHOLDS.flatTicksCritPolls,
      pollIntervalMs: parsed.pollIntervalMs ?? DEFAULT_THRESHOLDS.pollIntervalMs,
    };
  } catch {
    return { ...DEFAULT_THRESHOLDS };
  }
}

/** Persist custom thresholds to localStorage. */
export function saveThresholds(t: AlertThresholds): void {
  try {
    localStorage.setItem(THRESHOLD_STORE_KEY, JSON.stringify(t));
  } catch {
    // localStorage full or disabled — best-effort
  }
}

// ── Helpers ───────────────────────────────────────────────────────

export function ms(t: number): string {
  return t < 1000 ? `${Math.round(t)} ms` : `${(t / 1000).toFixed(1)} s`;
}

// ── Core evaluator ────────────────────────────────────────────────

/**
 * Evaluate connection-health metrics against configured alert thresholds
 * and return an aggregate status plus the list of active alerts.
 *
 * @param thresholds — optional custom thresholds; defaults to DEFAULT_THRESHOLDS
 *
 * This is a pure function — no side effects, no component state.
 */
export function evaluateHealth(
  metrics: HealthMetrics,
  velocity: number | null,
  flatPolls: number,
  thresholds: AlertThresholds = DEFAULT_THRESHOLDS,
): { status: HealthStatus; activeAlerts: HealthAlert[] } {
  const activeAlerts: HealthAlert[] = [];

  // 1. MT5 init latency
  if (metrics.mt5_timing) {
    if (metrics.mt5_timing.init_ms > thresholds.mt5InitCritMs) {
      activeAlerts.push({
        type: "mt5_latency",
        severity: "crit",
        message: `MT5 init took ${ms(metrics.mt5_timing.init_ms)} — above ${ms(thresholds.mt5InitCritMs)} critical threshold`,
      });
    } else if (metrics.mt5_timing.init_ms > thresholds.mt5InitWarnMs) {
      activeAlerts.push({
        type: "mt5_latency",
        severity: "warn",
        message: `MT5 init at ${ms(metrics.mt5_timing.init_ms)} — above ${ms(thresholds.mt5InitWarnMs)} warning threshold`,
      });
    }
  }

  // 2. CSV tick velocity
  // NOTE: When MT5 is connected AND there are already CSV ticks, zero
  // velocity is NORMAL — the system only appends ticks during snapshot
  // calls (user clicks Refresh).  There is no perpetual background
  // collector.  Downgrade velocity alerts to warn when the bridge
  // is alive and has data, instead of critical.
  const hasCsvData = Object.values(metrics.csv_ticks).some((n) => n > 0);
  // Only suppress CSV critical alerts when MT5 process is confirmed running
  // or was connected within the last 60 seconds.  A stale connection
  // timestamp (>60s ago) is NOT enough — the terminal may have crashed.
  const mt5Alive =
    metrics.mt5_configured &&
    (metrics.mt5_process_running ||
      (metrics.mt5_last_connected_at &&
        Date.now() - new Date(metrics.mt5_last_connected_at).getTime() < 60_000));
  const suppressCsvCritical = mt5Alive && hasCsvData;

  if (velocity !== null) {
    if (velocity < thresholds.csvVelocityCritTicksMin) {
      activeAlerts.push({
        type: "csv_velocity",
        severity: suppressCsvCritical ? "warn" : "crit",
        message: suppressCsvCritical
          ? `CSV ingestion at ${velocity.toLocaleString()} ticks/min — no background collector running (normal when MT5 is connected)`
          : `CSV ingestion at ${velocity.toLocaleString()} ticks/min — below ${thresholds.csvVelocityCritTicksMin} critical threshold`,
      });
    } else if (velocity < thresholds.csvVelocityWarnTicksMin) {
      activeAlerts.push({
        type: "csv_velocity",
        severity: "warn",
        message: `CSV ingestion at ${velocity.toLocaleString()} ticks/min — below ${thresholds.csvVelocityWarnTicksMin} warning threshold`,
      });
    }
  }

  // 3. Flat tick count
  // Same downgrade: when MT5 is connected and CSV has data, flat ticks
  // are expected (no perpetual collector).  Only flag as critical when
  // the bridge appears genuinely dead.
  if (flatPolls >= thresholds.flatTicksCritPolls) {
    activeAlerts.push({
      type: "ticks_stalled",
      severity: suppressCsvCritical ? "warn" : "crit",
      message: suppressCsvCritical
        ? `Tick count unchanged for ${flatPolls} polls — no background collector (normal)`
        : `Tick count unchanged for ${flatPolls} consecutive polls — data stream may have stalled`,
    });
  } else if (flatPolls >= thresholds.flatTicksWarnPolls) {
    activeAlerts.push({
      type: "ticks_stalled",
      severity: "warn",
      message: `Tick count flat for ${flatPolls} polls — expected ${Math.ceil(thresholds.pollIntervalMs / 1000 * (velocity ?? 0) / 60)} new ticks`,
    });
  }

  // ── Bridge offline detection ─────────────────────────────────────
  // When the Python subprocess consistently fails (pipeline diagnostics
  // have a lastError), the bridge is unreachable. Override to "offline"
  // so the dashboard shows "Bridge Offline" instead of "Critical" — the
  // zero velocity and stalled ticks alerts are symptoms, not root cause.
  if (metrics.bridge_unavailable) {
    // Still surface the underlying alerts so they're visible when expanded,
    // but elevate the status to "offline" so the collapsed badge reads
    // "Bridge Offline" instead of "Critical".
    return { status: "offline" as HealthStatus, activeAlerts };
  }

  // Aggregate status: any crit → red, any warn → amber, else green
  const hasCrit = activeAlerts.some((a) => a.severity === "crit");
  const hasWarn = activeAlerts.some((a) => a.severity === "warn");
  const status: HealthStatus = hasCrit ? "red" : hasWarn ? "amber" : "green";

  return { status, activeAlerts };
}
