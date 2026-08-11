import { describe, it, expect } from "vitest";
import { evaluateHealth, type HealthMetrics, DEFAULT_THRESHOLDS } from "../src/lib/health-logic";

// ── Boundary values ───────────────────────────────────────────────

const MT5 = {
  ok: 5_000,          // below warn threshold
  warn: 20_000,        // between warn (15k) and crit (30k)
  crit: 40_000,        // above crit threshold
} as const;

const VELOCITY = {
  ok: 100,             // above warn threshold (50)
  warn: 30,            // between crit (10) and warn (50)
  crit: 5,             // below crit threshold
} as const;

const FLAT = {
  ok: 0,               // below warn threshold (8)
  warn: 9,             // between warn (8) and crit (16)
  crit: 17,            // above crit threshold (16)
} as const;

// ── Helpers ───────────────────────────────────────────────────────

/** Build a minimal `HealthMetrics` object with a given MT5 init_ms. */
function metricsWithMt5(initMs: number): HealthMetrics {
  return {
    mt5_configured: true,
    mt5_server: "test-server",
    mt5_error: null,
    mt5_timing: { init_ms: initMs, login_ms: 500, total_ms: initMs + 500, timestamp: Date.now() },
    // Not running: the 27-combo threshold matrix expects the UNAFFECTED
    // crit severities (mt5Alive=false keeps csv_velocity/ticks_stalled at
    // crit instead of downgrading them to warn).
    mt5_process_running: false,
    mt5_last_connected_at: null,
    mt5_last_test: null,
    csv_size_bytes: 1024,
    csv_ticks: { R_75: 1000, R_100: 2000 },
    health_history: [],
    snapshot_phases: null,
    engine_version: "1.0.0",
    timestamp: Date.now(),    warmup_cache_hits: { R_75: 0, R_100: 0 },
  warmup_cache_misses: { R_75: 0, R_100: 0 },
    csv_cache_hit_ratio: 0,
    last_warmup_at: null,
    bridge_unavailable: false,
    pipeline_diagnostics: {
      lastGuardianReason: null,
      lastStderr: null,
      lastRetryCount: 0,
      lastError: null,
      lastUpdatedAt: null,
      staleDataSince: null,
    },
  };
}

/** Build a minimal `HealthMetrics` with `mt5_timing: null` (no MT5 data). */
const noMt5Metrics: HealthMetrics = {
  mt5_configured: false,
  mt5_server: null,
  mt5_error: null,
  mt5_timing: null,
  mt5_process_running: false,
  mt5_last_connected_at: null,
  mt5_last_test: null,
  csv_size_bytes: 0,
  csv_ticks: { R_75: 0, R_100: 0 },
  health_history: [],
  snapshot_phases: null,
  engine_version: null,
  timestamp: Date.now(),
  warmup_cache_hits: { R_75: 0, R_100: 0 },
  warmup_cache_misses: { R_75: 0, R_100: 0 },
  csv_cache_hit_ratio: 0,
  last_warmup_at: null,
  bridge_unavailable: false,
  pipeline_diagnostics: {
    lastGuardianReason: null,
    lastStderr: null,
    lastRetryCount: 0,
    lastError: null,
    lastUpdatedAt: null,
    staleDataSince: null,
  },
};

/**
 * Assert that the evaluateHealth result matches expectations.
 * We check status, alert count, and individual alert types+severities
 * without asserting exact message text (which would be brittle).
 */
function assertAlerts(
  actual: ReturnType<typeof evaluateHealth>,
  expected: {
    status: "green" | "amber" | "red";
    alerts: { type: string; severity: string }[];
  },
) {
  expect(actual.status).toBe(expected.status);
  expect(actual.activeAlerts).toHaveLength(expected.alerts.length);

  // Check each expected alert type+severity pair exists in the result
  for (const expectedAlert of expected.alerts) {
    const matching = actual.activeAlerts.filter(
      (a) => a.type === expectedAlert.type && a.severity === expectedAlert.severity,
    );
    expect(matching.length).toBeGreaterThanOrEqual(1);
  }
}

// ── Status matrix helper ──────────────────────────────────────────

/**
 * Given the severity level of each dimension, compute the expected
 * aggregate status: any crit → red, any warn → amber, else green.
 */
function aggregateStatus(
  mt5Level: "ok" | "warn" | "crit" | "none",
  velLevel: "ok" | "warn" | "crit" | "none",
  flatLevel: "ok" | "warn" | "crit",
): "green" | "amber" | "red" {
  const levels = [mt5Level, velLevel, flatLevel];
  if (levels.some((l) => l === "crit")) return "red";
  if (levels.some((l) => l === "warn")) return "amber";
  return "green";
}

type Level = "ok" | "warn" | "crit";
const ALL_LEVELS: Level[] = ["ok", "warn", "crit"];

// ── Tests ─────────────────────────────────────────────────────────

describe("evaluateHealth — alert thresholds", () => {
  // ── 3 × 3 × 3 = 27 exhaustive combinations ────────────────────

  describe.each(ALL_LEVELS)("mt5 init = %s", (mt5Level) => {
    describe.each(ALL_LEVELS)("velocity = %s", (velLevel) => {
      describe.each(ALL_LEVELS)("flat polls = %s", (flatLevel) => {
        const mt5Value = MT5[mt5Level];
        const velValue = VELOCITY[velLevel];
        const flatValue = FLAT[flatLevel];

        const expectedStatus = aggregateStatus(mt5Level, velLevel, flatLevel);

        // Build expected alert list
        const expectedAlerts: { type: string; severity: string }[] = [];
        if (mt5Level === "crit") expectedAlerts.push({ type: "mt5_latency", severity: "crit" });
        else if (mt5Level === "warn") expectedAlerts.push({ type: "mt5_latency", severity: "warn" });
        if (velLevel === "crit") expectedAlerts.push({ type: "csv_velocity", severity: "crit" });
        else if (velLevel === "warn") expectedAlerts.push({ type: "csv_velocity", severity: "warn" });
        if (flatLevel === "crit") expectedAlerts.push({ type: "ticks_stalled", severity: "crit" });
        else if (flatLevel === "warn") expectedAlerts.push({ type: "ticks_stalled", severity: "warn" });

        it(`returns status="${expectedStatus}" with ${expectedAlerts.length} alert(s)`, () => {
          const metrics = metricsWithMt5(mt5Value);
          const result = evaluateHealth(metrics, velValue, flatValue);
          assertAlerts(result, { status: expectedStatus, alerts: expectedAlerts });
        });
      });
    });
  });

  // ── Edge cases for null MT5 timing ────────────────────────────

  describe("when mt5_timing is null", () => {
    it.each([
      { vel: VELOCITY.ok, flat: FLAT.ok, expectedStatus: "green" as const, alertCount: 0 },
      { vel: VELOCITY.warn, flat: FLAT.ok, expectedStatus: "amber" as const, alertCount: 1 },
      { vel: VELOCITY.crit, flat: FLAT.ok, expectedStatus: "red" as const, alertCount: 1 },
      { vel: VELOCITY.ok, flat: FLAT.warn, expectedStatus: "amber" as const, alertCount: 1 },
      { vel: VELOCITY.ok, flat: FLAT.crit, expectedStatus: "red" as const, alertCount: 1 },
      { vel: VELOCITY.crit, flat: FLAT.crit, expectedStatus: "red" as const, alertCount: 2 },
    ])(
      "vel=$vel, flat=$flat → $expectedStatus ($alertCount alerts)",
      ({ vel, flat, expectedStatus, alertCount }) => {
        const result = evaluateHealth(noMt5Metrics, vel, flat);
        expect(result.status).toBe(expectedStatus);
        expect(result.activeAlerts).toHaveLength(alertCount);
      },
    );
  });

  // ── Edge case: null velocity ───────────────────────────────────

  describe("when velocity is null", () => {
    it("does not produce csv_velocity alerts", () => {
      const metrics = metricsWithMt5(MT5.ok);
      const result = evaluateHealth(metrics, null, FLAT.ok);
      expect(result.activeAlerts.filter((a) => a.type === "csv_velocity")).toHaveLength(0);
    });
  });

  // ── Exact boundary values ──────────────────────────────────────

  describe("boundary value testing", () => {
    it("fires no alert when MT5 init is exactly at warn threshold", () => {
      const metrics = metricsWithMt5(DEFAULT_THRESHOLDS.mt5InitWarnMs);
      const result = evaluateHealth(metrics, VELOCITY.ok, FLAT.ok);
      // 15_000 is NOT above 15_000, so should NOT warn
      expect(result.activeAlerts.filter((a) => a.type === "mt5_latency")).toHaveLength(0);
    });

    it("fires crit when MT5 init is exactly at crit threshold + 1", () => {
      const metrics = metricsWithMt5(DEFAULT_THRESHOLDS.mt5InitCritMs + 1);
      const result = evaluateHealth(metrics, VELOCITY.ok, FLAT.ok);
      expect(result.activeAlerts).toHaveLength(1);
      expect(result.activeAlerts[0].type).toBe("mt5_latency");
      expect(result.activeAlerts[0].severity).toBe("crit");
    });

    it("fires warn when velocity is exactly at warn threshold - 1", () => {
      const metrics = metricsWithMt5(MT5.ok);
      const result = evaluateHealth(metrics, DEFAULT_THRESHOLDS.csvVelocityWarnTicksMin - 1, FLAT.ok);
      expect(result.activeAlerts.filter((a) => a.type === "csv_velocity")[0]?.severity).toBe("warn");
    });

    it("fires crit when velocity is exactly at crit threshold", () => {
      const metrics = metricsWithMt5(MT5.ok);
      // crit threshold is 10; velocity < 10 => crit
      const result = evaluateHealth(metrics, DEFAULT_THRESHOLDS.csvVelocityCritTicksMin - 1, FLAT.ok);
      expect(result.activeAlerts.filter((a) => a.type === "csv_velocity")[0]?.severity).toBe("crit");
    });

    it("fires warning at exactly flatTicksWarnPolls", () => {
      const metrics = metricsWithMt5(MT5.ok);
      const result = evaluateHealth(metrics, VELOCITY.ok, DEFAULT_THRESHOLDS.flatTicksWarnPolls);
      // flatPolls >= flatTicksWarnPolls => warn
      expect(result.activeAlerts.filter((a) => a.type === "ticks_stalled")[0]?.severity).toBe("warn");
    });

    it("fires crit at exactly flatTicksCritPolls", () => {
      const metrics = metricsWithMt5(MT5.ok);
      const result = evaluateHealth(metrics, VELOCITY.ok, DEFAULT_THRESHOLDS.flatTicksCritPolls);
      // flatPolls >= flatTicksCritPolls => crit
      expect(result.activeAlerts.filter((a) => a.type === "ticks_stalled")[0]?.severity).toBe("crit");
    });
  });

  // ── Message format sanity ──────────────────────────────────────

  describe("alert message format", () => {
    it("includes the actual value in mt5_latency messages", () => {
      const metrics = metricsWithMt5(MT5.crit);
      const result = evaluateHealth(metrics, VELOCITY.ok, FLAT.ok);
      expect(result.activeAlerts[0].message).toContain("MT5 init");
      expect(result.activeAlerts[0].message).toContain("40");
    });

    it("includes the actual value in csv_velocity messages", () => {
      const metrics = metricsWithMt5(MT5.ok);
      const result = evaluateHealth(metrics, VELOCITY.warn, FLAT.ok);
      const velAlert = result.activeAlerts.find((a) => a.type === "csv_velocity");
      expect(velAlert?.message).toContain("CSV ingestion");
      expect(velAlert?.message).toContain("30");
    });

    it("includes poll count in ticks_stalled messages", () => {
      const metrics = metricsWithMt5(MT5.ok);
      const result = evaluateHealth(metrics, VELOCITY.ok, FLAT.crit);
      const flatAlert = result.activeAlerts.find((a) => a.type === "ticks_stalled");
      expect(flatAlert?.message).toContain("17");
    });
  });
});
