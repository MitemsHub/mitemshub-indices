import { z } from "zod";

export const accountModeSchema = z.enum(["own_account", "prop_firm"]);

export const tradingModeSchema = z.enum(["sniper", "active_trader"]);
export type TradingMode = z.infer<typeof tradingModeSchema>;

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

export type PropProfileResponse = z.infer<typeof propProfileResponseSchema>;

export const guardianStateSchema = z.enum([
  "forming",
  "actionable",
  "confirmed",
  "failing",
  "cancelled",
  "unavailable",
]);

export type GuardianState = z.infer<typeof guardianStateSchema>;

export const guardianStatusSchema = z.object({
  symbol: z.enum(["R_75", "R_100"]),
  guardian_state: guardianStateSchema,
  guardian_reason: z.string(),
  current_close: z.number().nullable(),
  generated_at: z.string(),
});

export type GuardianStatus = z.infer<typeof guardianStatusSchema>;

export const confidenceBreakdownSchema = z.object({
  model: z.number(),
  structure: z.number(),
  regime: z.number(),
  mean_reversion: z.number(),
  displacement: z.number(),
  momentum: z.number(),
  volatility: z.number(),
  garch: z.number(),
  session: z.number(),
  confluence: z.number(),
  weights: z.object({
    model: z.number(),
    structure: z.number(),
    regime: z.number(),
    mean_reversion: z.number(),
    displacement: z.number(),
    momentum: z.number(),
    volatility: z.number(),
    garch: z.number(),
    session: z.number(),
    confluence: z.number(),
  }),
  calibrated: z.number().optional(),
  final: z.number().optional(),
});

export type ConfidenceBreakdown = z.infer<typeof confidenceBreakdownSchema>;

export const evidenceSchema = z.object({
  evidence_id: z.string().optional(),
  name: z.string().optional(),
  factor: z.string().optional(),
  type: z.enum(["supporting", "contradicting", "neutral", "bullish", "bearish"]),
  description: z.string(),
  strength: z.number(),
  source: z.string(),
  value: z.unknown(),
  context: z.record(z.unknown()).optional(),
});

export type Evidence = z.infer<typeof evidenceSchema>;

export const timeframeAnalysisSchema = z.object({
  timeframe: z.string(),
  regime: z.string(),
  regime_confidence: z.number().optional(),
  structure_bias: z.number(),
  bos_up: z.number(),
  bos_down: z.number(),
  liquidity_sweep_up: z.number(),
  liquidity_sweep_down: z.number(),
  fvg_bullish_active: z.number(),
  fvg_bearish_active: z.number(),
  displacement_atr: z.number(),
  structure_bias_dup: z.number(),
  confidence: z.number(),
  direction_bias: z.string(),
  key_levels: z.object({
    recent_high: z.number(),
    recent_low: z.number(),
    invalidation: z.number().nullable(),
    target: z.number().nullable(),
  }),
});

export type TimeframeAnalysis = z.infer<typeof timeframeAnalysisSchema>;

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
  execution_stop: z.number().nullable().optional(),
  thesis_invalidation: z.number().nullable().optional(),
  primary_target: z.number().nullable().optional(),
  extended_target: z.number().nullable().optional(),
  hold_horizon_minutes: z.number().int().positive().nullable().optional(),
  execution_trigger_type: z.string().nullable().optional(),
  signal_strength: z.enum(["strong_buy", "weak_buy", "wait", "weak_sell", "strong_sell"]).nullable().optional(),
  position_sizing: z.enum(["full", "half", "none"]).nullable().optional(),
  reward_risk: z.number().nullable(),
  current_close: z.number().nullable(),
  guardian_state: z.enum(["forming", "actionable", "confirmed", "failing", "cancelled", "unavailable"]),
  guardian_reason: z.string(),
  invalidates_if: z.string().nullable().optional(),
  call_age_seconds: z.number().int().nonnegative().nullable().optional(),
  generated_at: z.string(),
  raw_features: z.record(z.string(), z.number()).nullable().optional(),
  snapshot_structure: z.record(z.string(), z.number()).nullable().optional(),
  model_long_probability: z.number().nullable().optional(),
  trading_mode: tradingModeSchema.nullable().optional(),
  risk_state: z.record(z.unknown()).nullable().optional(),
  account_mode: z.enum(["own_account", "prop_firm"]),
  prop_compliance: z.enum(["allowed", "allowed_with_adjustment", "blocked", "insufficient_account_state"]).nullable(),
  prop_adjusted_risk: z.number().nullable(),
  prop_block_reason: z.string().nullable(),
  prop_remaining_daily_buffer: z.number().nullable(),
  prop_remaining_overall_buffer: z.number().nullable(),
});

export type FreshCallResponse = z.infer<typeof freshCallResponseSchema>;
export type AccountMode = "own_account" | "prop_firm";
export type PropCompliance = "allowed" | "allowed_with_adjustment" | "blocked" | "insufficient_account_state";

export const propConnectionInputSchema = z.object({
  server: z.string().trim().nullable(),
  login: z.string().trim().nullable(),
  password: z.string().trim().nullable(),
  terminalPath: z.string().trim().nullable(),
  startingBalance: z.number().nullable().optional(),
});

export type PropConnectionInput = z.infer<typeof propConnectionInputSchema>;

export const propProfileRequestSchema = z.object({
  connection: z.object({
    server: z.string().trim().nullable(),
    login: z.string().trim().nullable(),
    password: z.string().trim().nullable(),
    terminalPath: z.string().trim().nullable(),
    startingBalance: z.number().nullable().optional(),
  }).nullable().optional(),
  startingBalance: z.number().nullable().optional(),
});

export type PropProfileRequest = z.infer<typeof propProfileRequestSchema>;

export const runCallRequestSchema = z.object({
  symbol: z.enum(["R_75", "R_100"]),
  account_mode: z.enum(["own_account", "prop_firm"]),
  trading_mode: tradingModeSchema.nullable().optional(),
  prop_account_state: z.object({
    profile: z.literal("blueberry_2step_funded"),
    startingBalance: z.number(),
    currentBalance: z.number(),
    currentEquity: z.number(),
    todaysRealizedLoss: z.number(),
    todaysFloatingLossExposure: z.number(),
    highImpactNewsLockout: z.boolean(),
  }).nullable().optional(),
  prop_connection: z.object({
    server: z.string().trim().nullable(),
    login: z.string().trim().nullable(),
    password: z.string().trim().nullable(),
    terminalPath: z.string().trim().nullable(),
    startingBalance: z.number().nullable().optional(),
  }).nullable().optional(),
});

export type RunCallRequest = z.infer<typeof runCallRequestSchema>;

export const executionModeSchema = z.enum(["paper", "live_mt5"]);
export type ExecutionMode = z.infer<typeof executionModeSchema>;

export const submitOrderRequestSchema = z.object({
  symbol: z.enum(["R_75", "R_100"]),
  direction_bias: z.enum(["buy", "sell"]),
  entry: z.number(),
  stop_loss: z.number(),
  take_profit: z.number(),
  execution_stop: z.number().nullable().optional(),
  thesis_invalidation: z.number().nullable().optional(),
  primary_target: z.number().nullable().optional(),
  extended_target: z.number().nullable().optional(),
  execution_mode: executionModeSchema,
  mt5_volume: z.number().min(0.01).optional(),
});

export const submitOrderResponseSchema = z.object({
  accepted: z.boolean(),
  position_id: z.string().nullable(),
  entry_price: z.number().nullable(),
  stop_loss: z.number().nullable(),
  take_profit: z.number().nullable(),
  message: z.string(),
});

export type SubmitOrderResponse = z.infer<typeof submitOrderResponseSchema>;

export const closePositionRequestSchema = z.object({
  position_id: z.string().nullable().optional(),
  execution_mode: executionModeSchema,
  mt5_ticket: z.number().nullable().optional(),
});

export const closePositionResponseSchema = z.object({
  closed: z.boolean(),
  message: z.string(),
});

export const trackedPositionSchema = z.object({
  position_id: z.string(),
  symbol: z.enum(["R_75", "R_100"]),
  direction: z.enum(["buy", "sell"]),
  entry_price: z.number(),
  stop_loss: z.number(),
  take_profit: z.number(),
  current_price: z.number().nullable(),
  opened_at: z.string(),
  execution_mode: executionModeSchema,
  mt5_ticket: z.number().nullable(),
});

export type TrackedPosition = z.infer<typeof trackedPositionSchema>;

export const confidenceTrendSchema = z.object({
  history: z.array(z.object({
    timestamp: z.string(),
    confidence: z.number(),
    calibrated_confidence: z.number(),
    direction_bias: z.string().nullable(),
    regime: z.string().nullable(),
  })),
  trend: z.enum(["improving", "stable", "degrading"]),
  volatility: z.number(),
});

export type ConfidenceTrend = z.infer<typeof confidenceTrendSchema>;

export const marketIntelligenceSchema = z.object({
  symbol: z.enum(["R_75", "R_100"]),
  current_price: z.number(),
  regime: z.string(),
  regime_confidence: z.number(),
  structure_bias: z.number(),
  structure_direction: z.string().optional(),
  call_direction: z.string().optional(),
  trend_direction: z.string(),
  volatility_state: z.string(),
  atr_ratio: z.number(),
  hurst_exponent: z.number(),
  entropy: z.number(),
  displacement_atr: z.number(),
  garch_sigma: z.number().nullable().optional(),
  garch_vol_regime: z.enum(["low", "normal", "high"]).nullable().optional(),
  garch_mean_revert_signal: z.number().nullable().optional(),
  session_quality: z.number().nullable().optional(),
  session_is_peak: z.boolean().optional(),
  key_levels: z.object({
    recent_swing_high: z.number(),
    recent_swing_low: z.number(),
    thesis_invalidation: z.number().nullable(),
    primary_target: z.number().nullable(),
    extended_target: z.number().nullable(),
  }),
  multi_timeframe: z.array(timeframeAnalysisSchema),
});

export type MarketIntelligence = z.infer<typeof marketIntelligenceSchema>;

export const evidenceSummarySchema = z.object({
  bullish: z.array(z.object({
    factor: z.string(),
    type: z.literal("bullish"),
    strength: z.number(),
    description: z.string(),
    source: z.string(),
  })),
  bearish: z.array(z.object({
    factor: z.string(),
    type: z.literal("bearish"),
    strength: z.number(),
    description: z.string(),
    source: z.string(),
  })),
  neutral: z.array(z.object({
    factor: z.string(),
    type: z.literal("neutral"),
    strength: z.number(),
    description: z.string(),
    source: z.string(),
  })),
  net_score: z.number(),
});

export type EvidenceSummary = z.infer<typeof evidenceSummarySchema>;

export const marketThesisSchema = z.object({
  direction: z.enum(["bullish", "bearish", "neutral"]),
  thesis: z.string(),
  invalidation_price: z.number().nullable(),
  invalidation_reason: z.string().nullable(),
  primary_target: z.number().nullable(),
  extended_target: z.number().nullable(),
  timeframe_alignment: z.enum(["full", "partial", "none"]),
  key_evidence: z.array(z.object({
    name: z.string(),
    description: z.string(),
    strength: z.number(),
    source: z.string(),
  })),
  counter_evidence: z.array(z.object({
    name: z.string(),
    description: z.string(),
    strength: z.number(),
    source: z.string(),
  })),
  confidence: z.number(),
});

export type MarketThesis = z.infer<typeof marketThesisSchema>;

export const tradePlanSchema = z.object({
  direction: z.enum(["long", "short"]),
  entry: z.number(),
  executionStop: z.number(),
  thesisInvalidation: z.number().nullable(),
  primaryTarget: z.number(),
  extendedTarget: z.number().nullable(),
  holdHorizonMinutes: z.number(),
  rewardRisk: z.number(),
  triggerType: z.string(),
  executionLevels: z.object({
    entry: z.number(),
    executionStop: z.number(),
    primaryTarget: z.number(),
    extendedTarget: z.number().nullable(),
    thesisInvalidation: z.number().nullable(),
  }),
  thesis: z.string(),
  invalidationReason: z.string(),
});

export type TradePlan = z.infer<typeof tradePlanSchema>;

export const alternativeScenarioSchema = z.object({
  scenario: z.string(),
  probability: z.number(),
  description: z.string(),
  what_would_change: z.string(),
  trigger_condition: z.string(),
});

export type AlternativeScenario = z.infer<typeof alternativeScenarioSchema>;

export const tradeProgressSchema = z.object({
  events: z.array(z.object({
    timestamp: z.string(),
    type: z.string(),
    description: z.string(),
    price: z.number().nullable(),
    guardian_state: z.string().nullable(),
    confidence: z.number().nullable(),
  })),
  current_phase: z.string(),
  time_in_phase: z.number().nullable(),
});

export type TradeProgress = z.infer<typeof tradeProgressSchema>;

export const riskAssessmentSchema = z.object({
  risk_per_trade: z.number(),
  max_daily_loss: z.number(),
  max_consecutive_losses: z.number(),
  current_daily_pnl: z.number(),
  consecutive_losses: z.number(),
  open_positions: z.number(),
  max_open_positions: z.number(),
  current_drawdown: z.number(),
  max_drawdown_limit: z.number(),
  risk_reward_ratio: z.number(),
  position_size: z.number(),
  max_position_size: z.number(),
  trades_today: z.number().optional(),
  equity: z.number().optional(),
});

export type RiskAssessment = z.infer<typeof riskAssessmentSchema>;

export const thesisInvalidationSchema = z.object({
  level: z.number(),
  reason: z.string(),
  distance_from_current: z.number(),
  distance_in_atr: z.number(),
  time_since_signal: z.number(),
  invalidation_triggers: z.array(z.string()),
});

export type ThesisInvalidation = z.infer<typeof thesisInvalidationSchema>;

export const aiNarrativeSchema = z.object({
  summary: z.string(),
  market_context: z.string(),
  thesis: z.string(),
  key_drivers: z.array(z.string()),
  uncertainties: z.array(z.string()),
  scenario_analysis: z.object({
    base_case: z.string(),
    bull_case: z.string(),
    bear_case: z.string(),
  }),
  recommendation: z.string(),
  confidence_rationale: z.string(),
});

export type AINarrative = z.infer<typeof aiNarrativeSchema>;

export const decisionHistorySchema = z.array(z.object({
  timestamp: z.string(),
  symbol: z.enum(["R_75", "R_100"]),
  call: z.enum(["buy_candidate", "sell_candidate", "stand_aside"]),
  trade_status: z.string(),
  confidence: z.number().nullable(),
  regime: z.string().nullable(),
  direction_bias: z.string().nullable(),
  outcome: z.string().nullable(),
  confidence_at_entry: z.number().nullable(),
  pnl: z.number().nullable(),
  rMultiple: z.number().nullable(),
  call_age_seconds: z.number().nullable(),
}));

export type DecisionHistory = z.infer<typeof decisionHistorySchema>;

export const postTradeLearningSchema = z.object({
  total_trades: z.number(),
  win_rate: z.number(),
  avg_r_multiple: z.number(),
  profit_factor: z.number(),
  avg_hold_time: z.number(),
  best_setup: z.string(),
  worst_setup: z.string(),
  regime_performance: z.record(z.object({
    trades: z.number(),
    win_rate: z.number(),
    avg_r: z.number(),
  })),
  recent_insights: z.array(z.string()),
  calibration_quality: z.number(),
  model_version: z.string(),
}).nullable();

export type PostTradeLearning = z.infer<typeof postTradeLearningSchema>;

export const garchForecastSchema = z.object({
  sigma: z.number(),
  sigma_annualized: z.number(),
  forecast_variance: z.number(),
  vol_regime: z.string(),
  vol_ratio: z.number(),
  z_score: z.number(),
  z_score_interpretation: z.string(),
  mean_revert_signal: z.number(),
  persistence: z.number(),
  persistence_label: z.string(),
  half_life: z.number(),
  long_run_vol: z.number(),
  alpha: z.number(),
  gamma: z.number(),
  actionable: z.string(),
}).nullable();

export type GarchForecast = z.infer<typeof garchForecastSchema>;

export const sessionQualitySchema = z.object({
  quality: z.number(),
  quality_label: z.string(),
  vol_rank: z.number(),
  is_peak_hour: z.boolean(),
  hour: z.number(),
  hour_display: z.string(),
  trend: z.number(),
  trend_label: z.string(),
  consistency: z.number(),
  total_hours_tracked: z.number(),
  total_observations: z.number(),
  actionable: z.string(),
}).nullable();

export type SessionQuality = z.infer<typeof sessionQualitySchema>;

export const generatorFingerprintSchema = z.object({
  detected_index: z.number(),
  detected_label: z.string(),
  confidence: z.number(),
  kurtosis: z.number(),
  skewness: z.number(),
  cluster_score: z.number(),
}).nullable();

export type GeneratorFingerprint = z.infer<typeof generatorFingerprintSchema>;

export const systemPerformanceSchema = z.object({
  total_trades: z.number(),
  wins: z.number(),
  losses: z.number(),
  win_rate: z.number(),
  profit_factor: z.number(),
  avg_r_multiple: z.number(),
  max_drawdown_pct: z.number(),
  max_drawdown_amount: z.number(),
  net_pnl: z.number(),
  gross_profit: z.number(),
  gross_loss: z.number(),
  avg_win: z.number(),
  avg_loss: z.number(),
  expectancy_r: z.number(),
  time_span: z.string(),
}).nullable();

export type SystemPerformance = z.infer<typeof systemPerformanceSchema>;

export const missedTradeLearningSchema = z.object({
  total_resolved: z.number(),
  missed_opportunities: z.number(),
  correct_stayouts: z.number(),
  miss_rate: z.number(),
  miss_rate_display: z.string(),
  pending_count: z.number(),
  range_miss_boost: z.number(),
  range_miss_boost_display: z.string(),
  recent_outcomes: z.array(z.object({
    symbol: z.string(),
    recorded_at: z.string().nullable(),
    resolved_at: z.string().nullable(),
    model_prediction: z.string(),
    confidence_at_record: z.number(),
    regime: z.string(),
    outcome: z.string(),
    price_at_record: z.number(),
    price_at_resolution: z.number().nullable(),
    price_move_atr: z.number().nullable(),
  })),
  status: z.enum(["no_data", "active"]),
  insight: z.string(),
}).nullable();

export type MissedTradeLearning = z.infer<typeof missedTradeLearningSchema>;

export const curveFittingTestSchema = z.object({
  symbol: z.string(),
  n_episodes: z.number(),
  n_ticks_per_episode: z.number(),
  aggregate: z.object({
    mean_win_rate: z.number(),
    mean_profit_factor: z.number(),
    mean_expectancy_r: z.number(),
    mean_net_pnl: z.number(),
    mean_signals: z.number(),
  }),
  consistency: z.object({
    win_rate_std: z.number(),
    profit_factor_std: z.number(),
    consistency_score: z.number(),
  }),
  curve_fitting: z.object({
    deflated_sharpe: z.number(),
    pbo_score: z.number(),
    monte_carlo_p_value: z.number(),
    edge_detected: z.boolean(),
  }),
  prop_firm: z.object({
    name: z.string(),
    total_breaches: z.number(),
    daily_loss_breaches: z.number(),
    drawdown_breaches: z.number(),
    risk_per_trade_breaches: z.number(),
    breach_rate: z.number(),
  }).nullable(),
  verdict: z.string(),
  explanation: z.string(),
  episodes: z.array(z.object({
    episode: z.number(),
    seed: z.number(),
    trades: z.number(),
    win_rate: z.number(),
    profit_factor: z.number(),
    expectancy_r: z.number(),
    net_pnl: z.number(),
    signals: z.number(),
  })),
  ran_at: z.string().nullable(),
}).nullable();

export type CurveFittingTest = z.infer<typeof curveFittingTestSchema>;

export const intelligencePayloadSchema = z.object({
  market_intelligence: marketIntelligenceSchema.nullable(),
  evidence_summary: evidenceSummarySchema.nullable(),
  market_thesis: marketThesisSchema.nullable(),
  confidence_breakdown: confidenceBreakdownSchema.nullable(),
  confidence_trend: confidenceTrendSchema.nullable(),
  trade_plan: tradePlanSchema.nullable(),
  alternative_scenario: alternativeScenarioSchema.nullable(),
  trade_progress: tradeProgressSchema.nullable(),
  risk_assessment: riskAssessmentSchema.nullable(),
  thesis_invalidation: thesisInvalidationSchema.nullable(),
  ai_narrative: aiNarrativeSchema.nullable(),
  decision_history: decisionHistorySchema.nullable(),
  post_trade_learning: postTradeLearningSchema.nullable(),
  garch_forecast: garchForecastSchema,
  session_quality: sessionQualitySchema,
  generator_fingerprint: generatorFingerprintSchema,
  missed_trade_learning: missedTradeLearningSchema,
  curve_fitting_test: curveFittingTestSchema,
  system_performance: systemPerformanceSchema,
});

export type IntelligencePayload = z.infer<typeof intelligencePayloadSchema>;