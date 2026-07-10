import { z } from "zod";

export const accountModeSchema = z.enum(["own_account", "prop_firm"]);

export const propComplianceSchema = z.enum([
  "allowed",
  "allowed_with_adjustment",
  "blocked",
  "insufficient_account_state",
]);

export const propAccountStateSchema = z.object({
  profile: z.literal("blueberry_2step_funded"),
  startingBalance: z.number(),
  currentBalance: z.number(),
  currentEquity: z.number(),
  todaysRealizedLoss: z.number(),
  todaysFloatingLossExposure: z.number(),
  highImpactNewsLockout: z.boolean(),
});

export const propTelemetryStatusSchema = z.enum([
  "live_confirmed",
  "own_account_fallback",
  "live_unavailable",
]);

export const propTelemetryStateSchema = z.object({
  status: propTelemetryStatusSchema,
  message: z.string(),
});

export const propProfileResponseSchema = propAccountStateSchema.extend({
  telemetry: propTelemetryStateSchema,
});

export const freshCallResponseSchema = z.object({
  symbol: z.enum(["R_75", "R_100"]),
  call: z.enum(["buy_candidate", "sell_candidate", "stand_aside"]),
  alert_type: z.string(),
  trade_status: z.string(),
  confidence: z.number().nullable(),
  regime: z.string().nullable(),
  direction_bias: z.string().nullable(),
  why: z.string().nullable(),
  wait_for: z.string().nullable(),
  decision_summary: z.string().nullable(),
  entry_area: z.string().nullable(),
  stop_area: z.string().nullable(),
  target_area: z.string().nullable(),
  entry: z.number().nullable(),
  stop_loss: z.number().nullable(),
  take_profit: z.number().nullable(),
  reward_risk: z.number().nullable(),
  generated_at: z.string(),
  account_mode: accountModeSchema,
  prop_compliance: propComplianceSchema.nullable(),
  prop_adjusted_risk: z.number().nullable(),
  prop_block_reason: z.string().nullable(),
  prop_remaining_daily_buffer: z.number().nullable(),
  prop_remaining_overall_buffer: z.number().nullable(),
});

export const propConnectionInputSchema = z.object({
  server: z.string().trim().nullable(),
  login: z.string().trim().nullable(),
  password: z.string().trim().nullable(),
  terminalPath: z.string().trim().nullable(),
  startingBalance: z.number().nullable().optional(),
});

export const propProfileRequestSchema = z.object({
  connection: propConnectionInputSchema.nullable().optional(),
  startingBalance: z.number().nullable().optional(),
});

export const runCallRequestSchema = z.object({
  symbol: z.enum(["R_75", "R_100"]),
  account_mode: accountModeSchema,
  prop_account_state: propAccountStateSchema.nullable().optional(),
  prop_connection: propConnectionInputSchema.nullable().optional(),
});

export type FreshCallResponse = z.infer<typeof freshCallResponseSchema>;
export type AccountMode = z.infer<typeof accountModeSchema>;
export type PropCompliance = z.infer<typeof propComplianceSchema>;
export type PropConnectionInput = z.infer<typeof propConnectionInputSchema>;
export type PropProfileRequest = z.infer<typeof propProfileRequestSchema>;
export type RunCallRequest = z.infer<typeof runCallRequestSchema>;
export type PropProfileResponse = z.infer<typeof propProfileResponseSchema>;
