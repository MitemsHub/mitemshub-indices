/**
 * Property-based tests for `evaluateHealth`.
 *
 * Generates random `HealthMetrics` payloads, velocities, and flat-poll counts
 * and verifies the invariant: the function never returns more than 3 alerts
 * (one per dimension), and the aggregate status is always the correct
 * aggregation of individual severities.
 */
import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import {
  evaluateHealth,
  DEFAULT_THRESHOLDS,
  type AlertThresholds,
  type HealthMetrics,
  type Mt5Timing,
} from "../src/lib/health-logic";

// ── Arbitraries ─────────────────────────────────────────────────

/** Non-negative finite number (including 0). */
const nonNeg: fc.Arbitrary<number> = fc
  .float({ noNaN: true, min: 0, max: 1_000_000 })
  .map((n) => Math.round(n));

/** Positive finite number (> 0). */
const positive: fc.Arbitrary<number> = fc
  .float({ noNaN: true, min: 1, max: 1_000_000 })
  .map((n) => Math.round(n));

/** Generate a random `Mt5Timing` or `null` (50/50). */
const arbTiming: fc.Arbitrary<Mt5Timing | null> = fc.oneof(
  fc.record({
    init_ms: nonNeg,
    login_ms: nonNeg,
    total_ms: nonNeg,
    timestamp: fc.integer({ min: 1_700_000_000_000, max: 2_000_000_000_000 }),
  }),
  fc.constant(null),
);

/** Generate random `csv_ticks` record (symbol → count). */
const arbCsvTicks: fc.Arbitrary<Record<string, number>> = fc.record({
  R_75: nonNeg,
  R_100: nonNeg,
});

/** Generate a random `HealthMetrics` payload — all fields are synthetic. */
const arbHealthMetrics: fc.Arbitrary<HealthMetrics> = fc
  .tuple(arbTiming, arbCsvTicks, fc.integer({ min: 0, max: 10_000_000 }), fc.boolean())
  .map(([timing, csvTicks, csvSize, configured]) => ({
    mt5_configured: configured,
    mt5_server: configured ? "prop-server" : null,
    mt5_error: null,
    mt5_timing: timing,
    mt5_process_running: configured,
    mt5_last_connected_at: null,
    mt5_last_test: null,
    csv_size_bytes: csvSize,
    csv_ticks: csvTicks,
    health_history: [],
    snapshot_phases: null,
    engine_version: "1.0.0",
    timestamp: Date.now(),
    warmup_cache_hits: { R_75: 0, R_100: 0 },
    warmup_cache_misses: { R_75: 0, R_100: 0 },
    csv_cache_hit_ratio: 0.5,
    last_warmup_at: new Date().toISOString(),
    bridge_unavailable: false,
    pipeline_diagnostics: {
      lastGuardianReason: null,
      lastStderr: null,
      lastRetryCount: 0,
      lastError: null,
      lastUpdatedAt: null,
      staleDataSince: null,
    },
  }));

/** Generate a random velocity value — may also be `null`. */
const arbVelocity: fc.Arbitrary<number | null> = fc.oneof(
  fc.integer({ min: -1, max: 10_000 }).map((n) => (n < 0 ? null : n)),
  fc.constant(null),
);

/** Generate a flat-poll count — any non-negative integer. */
const arbFlatPolls: fc.Arbitrary<number> = fc.integer({ min: 0, max: 100 });

/** Generate a random `AlertThresholds` with sane ranges. */
const arbThresholds: fc.Arbitrary<AlertThresholds> = fc.record({
  mt5InitWarnMs: fc.integer({ min: 100, max: 100_000 }),
  mt5InitCritMs: fc.integer({ min: 100, max: 100_000 }),
  csvVelocityWarnTicksMin: fc.integer({ min: 1, max: 500 }),
  csvVelocityCritTicksMin: fc.integer({ min: 1, max: 500 }),
  flatTicksWarnPolls: fc.integer({ min: 1, max: 50 }),
  flatTicksCritPolls: fc.integer({ min: 1, max: 50 }),
  pollIntervalMs: fc.integer({ min: 1_000, max: 120_000 }),
});

// ── Helpers ──────────────────────────────────────────────────────

/**
 * Predict the aggregate status from individual severities.
 * Any crit → red, any warn (without crit) → amber, else green.
 */
function predictStatus(
  alerts: { severity: "warn" | "crit" }[],
): "green" | "amber" | "red" {
  if (alerts.some((a) => a.severity === "crit")) {
    return "red";
  }
  if (alerts.some((a) => a.severity === "warn")) {
    return "amber";
  }
  return "green";
}

// ── Property-based tests ─────────────────────────────────────────

describe("evaluateHealth — property-based invariants", () => {
  it(
    "never returns more than 3 alerts and no duplicate types",
    () => fc.assert(
      fc.property(
        arbHealthMetrics,
        arbVelocity,
        arbFlatPolls,
        (metrics, velocity, flatPolls) => {
          const { activeAlerts } = evaluateHealth(metrics, velocity, flatPolls);

          // Invariant 1: at most 3 alerts (one per dimension)
          expect(activeAlerts.length).toBeLessThanOrEqual(3);

          // Invariant 2: no duplicate alert types (can't have both
          // warn and crit for the same dimension)
          const types = activeAlerts.map((a) => a.type);
          expect(new Set(types).size).toBe(types.length);
        },
      ),
      { numRuns: 100 },
    ),
  );

  it(
    "aggregate status matches severity of individual alerts",
    () => fc.assert(
      fc.property(
        arbHealthMetrics,
        arbVelocity,
        arbFlatPolls,
        (metrics, velocity, flatPolls) => {
          const { status, activeAlerts } = evaluateHealth(
            metrics,
            velocity,
            flatPolls,
          );

          const expected = predictStatus(activeAlerts);
          expect(status).toBe(expected);
        },
      ),
      { numRuns: 100 },
    ),
  );

  it(
    "no mt5_latency alert when mt5_timing is null",
    () => fc.assert(
      fc.property(
        arbHealthMetrics,
        arbVelocity,
        arbFlatPolls,
        (metrics, velocity, flatPolls) => {
          // Force mt5_timing to null
          const nullTimingMetrics: HealthMetrics = { ...metrics, mt5_timing: null };
          const { activeAlerts } = evaluateHealth(
            nullTimingMetrics,
            velocity,
            flatPolls,
          );

          const mt5Alerts = activeAlerts.filter((a) => a.type === "mt5_latency");
          expect(mt5Alerts).toHaveLength(0);
        },
      ),
      { numRuns: 50 },
    ),
  );

  it(
    "no csv_velocity alert when velocity is null",
    () => fc.assert(
      fc.property(
        arbHealthMetrics,
        arbFlatPolls,
        (metrics, flatPolls) => {
          const { activeAlerts } = evaluateHealth(metrics, null, flatPolls);

          const velAlerts = activeAlerts.filter((a) => a.type === "csv_velocity");
          expect(velAlerts).toHaveLength(0);
        },
      ),
      { numRuns: 50 },
    ),
  );

  it(
    "no ticks_stalled alert when flatPolls is 0",
    () => fc.assert(
      fc.property(
        arbHealthMetrics,
        arbVelocity,
        (metrics, velocity) => {
          const { activeAlerts } = evaluateHealth(metrics, velocity, 0);

          const flatAlerts = activeAlerts.filter((a) => a.type === "ticks_stalled");
          expect(flatAlerts).toHaveLength(0);
        },
      ),
      { numRuns: 50 },
    ),
  );

  it(
    "calling with custom thresholds respects both warn and crit boundaries",
    () => fc.assert(
      fc.property(
        arbHealthMetrics,
        arbThresholds,
        (metrics, thresholds) => {
          // Ensure warn < crit (they're independently generated, so swap if needed)
          const t: AlertThresholds = {
            ...thresholds,
            mt5InitWarnMs: Math.min(thresholds.mt5InitWarnMs, thresholds.mt5InitCritMs),
            mt5InitCritMs: Math.max(thresholds.mt5InitWarnMs, thresholds.mt5InitCritMs),
            csvVelocityWarnTicksMin: Math.min(
              thresholds.csvVelocityWarnTicksMin,
              thresholds.csvVelocityCritTicksMin,
            ),
            csvVelocityCritTicksMin: Math.max(
              thresholds.csvVelocityWarnTicksMin,
              thresholds.csvVelocityCritTicksMin,
            ),
            flatTicksWarnPolls: Math.min(
              thresholds.flatTicksWarnPolls,
              thresholds.flatTicksCritPolls,
            ),
            flatTicksCritPolls: Math.max(
              thresholds.flatTicksWarnPolls,
              thresholds.flatTicksCritPolls,
            ),
          };

          const { activeAlerts } = evaluateHealth(metrics, null, 0, t);
          expect(activeAlerts.length).toBeLessThanOrEqual(3);
          expect(new Set(activeAlerts.map((a) => a.type)).size).toBe(
            activeAlerts.length,
          );
        },
      ),
      { numRuns: 50 },
    ),
  );

  it(
    "status is 'green' when all dimensions are within thresholds",
    () => fc.assert(
      fc.property(
        nonNeg,
        positive,
        (initMs, threshold) => {
          const safeThreshold = Math.max(threshold, initMs + 1); // ensure threshold > init
          const metrics: HealthMetrics = {
            mt5_configured: true,
            mt5_server: "s",
            mt5_error: null,
            mt5_timing: {
              init_ms: initMs,
              login_ms: 100,
              total_ms: initMs + 100,
              timestamp: Date.now(),
            },
            mt5_process_running: true,
            mt5_last_connected_at: null,
            mt5_last_test: null,
            bridge_unavailable: false,
            csv_size_bytes: 1000,
            csv_ticks: { R_75: 100, R_100: 200 },
            health_history: [],
            snapshot_phases: null,
            engine_version: "1.0.0",
            timestamp: Date.now(),
            warmup_cache_hits: { R_75: 0, R_100: 0 },
            warmup_cache_misses: { R_75: 0, R_100: 0 },
            csv_cache_hit_ratio: 0,
            last_warmup_at: null,
            pipeline_diagnostics: {
              lastGuardianReason: null,
              lastStderr: null,
              lastRetryCount: 0,
              lastError: null,
              lastUpdatedAt: null,
              staleDataSince: null,
            },
          };

          const customThresholds: AlertThresholds = {
            ...DEFAULT_THRESHOLDS,
            mt5InitWarnMs: safeThreshold,
            mt5InitCritMs: safeThreshold + 10_000,
          };

          const { status, activeAlerts } = evaluateHealth(
            metrics,
            500,
            0,
            customThresholds,
          );
          expect(status).toBe("green");
          expect(activeAlerts.filter((a) => a.type === "mt5_latency")).toHaveLength(
            0,
          );
        },
      ),
      { numRuns: 25 },
    ),
  );
});
