import { NextResponse } from "next/server";
import { readFile } from "node:fs/promises";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { getLatestCall, getSystemStatus, getRecentHistory, readPreparedCall } from "../../../src/lib/engine-bridge";

function isCallUnavailable(call: any): boolean {
  return (
    !call ||
    call.guardian_state === "unavailable"
  );
}

function intelligenceEmptyResponse(usingPrepared = false) {
  return {
    market_intelligence: null,
    evidence_summary: null,
    market_thesis: null,
    confidence_breakdown: null,
    confidence_trend: null,
    trade_plan: null,
    alternative_scenario: null,
    trade_progress: null,
    risk_assessment: null,
    thesis_invalidation: null,
    ai_narrative: null,
    decision_history: [],
    post_trade_learning: null,
    garch_forecast: null,
    session_quality: null,
    generator_fingerprint: null,
    missed_trade_learning: null,
    curve_fitting_test: null,
    using_prepared_call: usingPrepared,
  };
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const call = body.call;
    const rawHistory = Array.isArray(body.history) ? body.history : [];
    const symbol = (body.symbol ?? call?.symbol ?? "R_100") as "R_75" | "R_100";
    const history = rawHistory.filter((entry: any) => entry?.symbol === symbol);

    if (!call || isCallUnavailable(call)) {
      return NextResponse.json(intelligenceEmptyResponse());
    }

    // Get system status (fast, no subprocess).
    // Intentionally SKIP getCurrentPropProfile here — it spawns a Python subprocess
    // to connect to MT5 for the prop account, which can take up to 20s when MT5 is
    // busy. The intelligence panels don't need live prop data; they use call.risk_state
    // which is already set by the Python snapshot. Removing this call cuts intelligence
    // response time from ~20s to <100ms.
    const systemStatus = await getSystemStatus();

    const intelligence = await buildIntelligencePayload(
      symbol,
      call,
      systemStatus,
      null,  // propProfile — not needed by intelligence panels
      history
    );

    return NextResponse.json({
      ...intelligence,
      using_prepared_call: false,
    });
  } catch (err) {
    console.error('[intelligence] POST error:', err);
    return NextResponse.json(
      { error: "Failed to build intelligence payload" },
      { status: 500 }
    );
  }
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const symbol = (searchParams.get("symbol") ?? "R_100") as "R_75" | "R_100";
  const includeHistory = searchParams.get("history") === "true";
  const tradingMode = (searchParams.get("trading_mode") ?? "sniper") as
    | "sniper"
    | "active_trader";

  try {
    // Same as POST: skip the expensive getCurrentPropProfile() call.
    // Use a race with a 3s timeout to avoid blocking on MT5 prop profile.
    const [currentCall, systemStatus, historyResult, preparedCall] = await Promise.all([
      getLatestCall(symbol, tradingMode),
      getSystemStatus(),
      includeHistory ? getRecentHistory(symbol) : Promise.resolve({ history: [] }),
      readPreparedCall(symbol),
    ]);

    // Use prepared call as fallback if current call is unavailable
    const callToUse = !isCallUnavailable(currentCall) ? currentCall : preparedCall;

    if (!callToUse || isCallUnavailable(callToUse)) {
      return NextResponse.json(intelligenceEmptyResponse(!!preparedCall && isCallUnavailable(currentCall)));
    }

    const intelligence = await buildIntelligencePayload(
      symbol,
      callToUse,
      systemStatus,
      null,
      historyResult.history
    );

    return NextResponse.json({
      ...intelligence,
      using_prepared_call: !!preparedCall && isCallUnavailable(currentCall),
    });
  } catch (err) {
    console.error('[intelligence] GET error:', err);
    return NextResponse.json(
      { error: "Failed to build intelligence payload" },
      { status: 500 }
    );
  }
}

async function buildIntelligencePayload(
  symbol: "R_75" | "R_100",
  currentCall: any,
  systemStatus: any,
  propProfile: any,
  history: any[]
) {
  const marketIntelligence = buildMarketIntelligence(currentCall, symbol);
  const evidenceSummary = buildEvidenceSummary(currentCall);
  const marketThesis = buildMarketThesis(currentCall);
  const confidenceBreakdown = buildConfidenceBreakdown(currentCall);
  const confidenceTrend = buildConfidenceTrend(history);
  const tradePlan = buildTradePlan(currentCall);
  const alternativeScenario = buildAlternativeScenario(currentCall);
  const tradeProgress = buildTradeProgress(currentCall, history);
  const riskAssessment = buildRiskAssessment(currentCall, propProfile);
  const thesisInvalidation = buildThesisInvalidation(currentCall);
  const aiNarrative = buildAINarrative(currentCall);
  const decisionHistory = buildDecisionHistory(history);
  const postTradeLearning = buildPostTradeLearning(history);

  const garchForecast = buildGarchForecast(currentCall);
  const sessionQuality = buildSessionQuality(currentCall);
  const generatorFingerprint = buildGeneratorFingerprint(currentCall);    const missedTradeLearning = buildMissedTradeLearning();
  const curveFittingTest = buildCurveFittingTest();

  return {
    market_intelligence: marketIntelligence,
    evidence_summary: evidenceSummary,
    market_thesis: marketThesis,
    confidence_breakdown: confidenceBreakdown,
    confidence_trend: confidenceTrend,
    trade_plan: tradePlan,
    alternative_scenario: alternativeScenario,
    trade_progress: tradeProgress,
    risk_assessment: riskAssessment,
    thesis_invalidation: thesisInvalidation,
    ai_narrative: aiNarrative,
    decision_history: decisionHistory,
    post_trade_learning: postTradeLearning,
    garch_forecast: garchForecast,
    session_quality: sessionQuality,
    generator_fingerprint: generatorFingerprint,
    missed_trade_learning: missedTradeLearning,
    curve_fitting_test: curveFittingTest,
  };
}

function buildTfRow(
  timeframe: string,
  features: Record<string, number>,
  prefix: string,
  confidence: number,
  overrideRegime: string,
  overrideStructure: Record<string, number>,
  thesisInvalidation: number | null,
  primaryTarget: number | null,
): any {
  const sb = features[`${prefix}structure_bias`] ?? features.structure_bias ?? 0;
  const regime = features[`${prefix}regime_trend_up`]
    ? "trend_up"
    : features[`${prefix}regime_trend_down`]
    ? "trend_down"
    : features[`${prefix}regime_range`]
    ? "range"
    : features[`${prefix}regime_volatile`]
    ? "volatile"
    : features[`${prefix}regime_compression`]
    ? "compression"
    : features[`${prefix}regime_unknown`]
    ? "unknown"
    : overrideRegime;

  const dir = sb > 0.2 ? "bullish" : sb < -0.2 ? "bearish" : "neutral";

  return {
    timeframe,
    regime,
    structure_bias: sb,
    bos_up: features[`${prefix}bos_up`] ?? features.bos_up ?? 0,
    bos_down: features[`${prefix}bos_down`] ?? features.bos_down ?? 0,
    liquidity_sweep_up: features[`${prefix}liquidity_sweep_up`] ?? features.liquidity_sweep_up ?? 0,
    liquidity_sweep_down: features[`${prefix}liquidity_sweep_down`] ?? features.liquidity_sweep_down ?? 0,
    fvg_bullish_active: features[`${prefix}fvg_bullish_active`] ?? features.fvg_bullish_active ?? 0,
    fvg_bearish_active: features[`${prefix}fvg_bearish_active`] ?? features.fvg_bearish_active ?? 0,
    displacement_atr: features[`${prefix}displacement_atr`] ?? features.displacement_atr ?? 0,
    structure_bias_dup: sb,
    confidence,
    direction_bias: dir,
    key_levels: {
      recent_high: features[`${prefix}recent_swing_high`] ?? overrideStructure.recent_swing_high ?? 0,
      recent_low: features[`${prefix}recent_swing_low`] ?? overrideStructure.recent_swing_low ?? 0,
      invalidation: thesisInvalidation,
      target: primaryTarget,
    },
  };
}

function buildMarketIntelligence(call: any, symbol: string) {
  const features = call.raw_features || {};
  const structure = call.snapshot_structure || {};

  const sb = features.structure_bias || 0;
  const atrRatio = features.atr_ratio || 1.0;
  const conf = call.confidence || 0.5;
  const modelProb = call.model_long_probability;
  const regime = call.regime || "unknown";

    const callDirection = call.direction_bias === "buy" ? "bullish" : call.direction_bias === "sell" ? "bearish" : "neutral";
    // Structure direction comes from the feature-derived structure_bias, NOT the call direction.
    // This keeps the Market Intelligence panel as an honest reflection of raw market structure
    // independent of the decision engine's final call. Users can see when structure says
    // one thing but the model + risk engine decide another.
    const structureDirection = sb > 0.2 ? "bullish" : sb < -0.2 ? "bearish" : "neutral";

    const trendDirection = _computeTrendDirection(call, features, structure);
    const volatilityState = atrRatio > 1.4 ? "high" : atrRatio < 0.7 ? "low" : "normal";

    const swingHigh = structure.recent_swing_high || 0;
    const swingLow = structure.recent_swing_low || 0;
    const rangeWidth = swingHigh > 0 && swingLow > 0 ? Math.abs(swingHigh - swingLow) : 0;
    const hasSwingRange = swingHigh > 0 && swingLow > 0;

    let thesisInvalidation = call.thesis_invalidation ?? null;
    let primaryTarget = call.primary_target ?? null;
    let extendedTarget = call.extended_target ?? null;

    if (hasSwingRange && thesisInvalidation == null) {
      if (sb > 0.1) {
        thesisInvalidation = swingLow;
        primaryTarget = swingHigh;
        extendedTarget = swingHigh + rangeWidth * 0.5;
      } else if (sb < -0.1) {
        thesisInvalidation = swingHigh;
        primaryTarget = swingLow;
        extendedTarget = swingLow - rangeWidth * 0.5;
      } else {
        thesisInvalidation = swingLow;
        primaryTarget = swingHigh;
        extendedTarget = swingHigh + rangeWidth * 0.5;
      }
    }

    const primaryTf = buildTfRow("1M", features, "", conf, regime, structure, thesisInvalidation, primaryTarget);
    const higherTf = buildTfRow("5M", features, "htf_", conf * 0.95, regime, structure, thesisInvalidation, primaryTarget);

    const synth15M = buildRealTfRow("15M", features, "confirmation_", conf, structure, call);
    const synth1H = buildRealTfRow("1H", features, "setup_", conf, structure, call);
    const synth4H = buildRealTfRow("4H", features, "bias_", conf, structure, call);

    return {
      symbol,
      current_price: call.current_close || 0,
      regime,
      regime_confidence: call.confidence || 0.5,
      structure_bias: sb,
      structure_direction: structureDirection,
      call_direction: callDirection,
      trend_direction: trendDirection,
      volatility_state: volatilityState,
      atr_ratio: atrRatio,
      hurst_exponent: features.hurst_exponent || 0.5,
      entropy: features.entropy || 0.5,
      displacement_atr: features.displacement_atr || 0,
      garch_sigma: features.garch_sigma ?? null,
      garch_vol_regime: features.garch_vol_regime === 0 ? "low" : features.garch_vol_regime === 2 ? "high" : features.garch_vol_regime !== undefined ? "normal" : null,
      garch_mean_revert_signal: features.garch_mean_revert_signal ?? null,
      session_quality: features.session_quality ?? null,
      session_is_peak: features.session_is_peak === 1.0,
      key_levels: {
        recent_swing_high: swingHigh || 0,
        recent_swing_low: swingLow || 0,
        thesis_invalidation: thesisInvalidation,
        primary_target: primaryTarget,
        extended_target: extendedTarget,
      },
      multi_timeframe: [synth4H, synth1H, synth15M, primaryTf, higherTf],
    };
}

function buildEvidenceSummary(call: any) {
  const features = call.raw_features || {};

  const evidence = [];

  if (features.bos_up) evidence.push({ factor: "Break of Structure Up", type: "bullish", strength: 0.8, description: "Price broke above recent swing high", source: "structure" });
  if (features.bos_down) evidence.push({ factor: "Break of Structure Down", type: "bearish", strength: 0.8, description: "Price broke below recent swing low", source: "structure" });
  if (features.internal_bos_up) evidence.push({ factor: "Internal BOS Up", type: "bullish", strength: 0.6, description: "Internal break of structure confirms trend", source: "structure" });
  if (features.internal_bos_down) evidence.push({ factor: "Internal BOS Down", type: "bearish", strength: 0.6, description: "Internal break of structure confirms trend", source: "structure" });

  if (features.liquidity_sweep_down) evidence.push({ factor: "Liquidity Sweep Down Reclaimed", type: "bullish", strength: 0.7, description: "Price swept below lows then reclaimed", source: "structure" });
  if (features.liquidity_sweep_up) evidence.push({ factor: "Liquidity Sweep Up Rejected", type: "bearish", strength: 0.7, description: "Price swept above highs then rejected", source: "structure" });

  if (features.fvg_bullish_active) evidence.push({ factor: "Bullish FVG Active", type: "bullish", strength: 0.6, description: "Fair value gap being tested as support", source: "structure" });
  if (features.fvg_bearish_active) evidence.push({ factor: "Bearish FVG Active", type: "bearish", strength: 0.6, description: "Fair value gap being tested as resistance", source: "structure" });

  if (features.equal_highs) evidence.push({ factor: "Equal Highs", type: "bearish", strength: 0.5, description: "Double top formation detected", source: "structure" });
  if (features.equal_lows) evidence.push({ factor: "Equal Lows", type: "bullish", strength: 0.5, description: "Double bottom formation detected", source: "structure" });

  const regime = call.regime || "unknown";
  if (regime === "trend_up") evidence.push({ factor: "Trending Up Regime", type: "bullish", strength: 0.7, description: "Market in persistent uptrend", source: "regime" });
  else if (regime === "trend_down") evidence.push({ factor: "Trending Down Regime", type: "bearish", strength: 0.7, description: "Market in persistent downtrend", source: "regime" });
  else if (regime === "volatile") evidence.push({ factor: "Volatile Regime", type: "neutral", strength: 0.4, description: "High volatility environment", source: "regime" });
  else if (regime === "compression") evidence.push({ factor: "Compression Regime", type: "neutral", strength: 0.3, description: "Low volatility compression", source: "regime" });
  else if (regime === "range") evidence.push({ factor: "Range Regime", type: "neutral", strength: 0.4, description: "Mean-reverting range market", source: "regime" });

  const slope = features.slope_20_atr || 0;
  if (slope > 0.1) evidence.push({ factor: "Positive Momentum", type: "bullish", strength: Math.min(Math.abs(slope) * 2, 0.8), description: "Positive price momentum", source: "momentum" });
  else if (slope < -0.1) evidence.push({ factor: "Negative Momentum", type: "bearish", strength: Math.min(Math.abs(slope) * 2, 0.8), description: "Negative price momentum", source: "momentum" });

  const displacement = features.displacement_atr || 0;
  if (displacement > 1.5) evidence.push({ factor: "Strong Displacement", type: "bullish", strength: Math.min(displacement / 3, 0.9), description: "Strong directional price movement", source: "displacement" });
  else if (displacement < -1.5) evidence.push({ factor: "Strong Negative Displacement", type: "bearish", strength: Math.min(Math.abs(displacement) / 3, 0.9), description: "Strong negative price movement", source: "displacement" });

  const atrRatio = features.atr_ratio || 1.0;
  if (atrRatio > 1.5) evidence.push({ factor: "High Volatility", type: "bearish", strength: 0.6, description: "Expanded volatility increases risk", source: "volatility" });
  else if (atrRatio < 0.7) evidence.push({ factor: "Low Volatility", type: "bullish", strength: 0.4, description: "Compressed volatility favors breakout", source: "volatility" });

  const hurst = features.hurst_exponent || 0.5;
  if (hurst > 0.6) evidence.push({ factor: "Persistent Trend", type: "neutral", strength: 0.5, description: "Trend likely to persist (Hurst > 0.6)", source: "regime" });
  else if (hurst < 0.4) evidence.push({ factor: "Mean Reversion Likely", type: "neutral", strength: 0.5, description: "Mean reversion likely (Hurst < 0.4)", source: "regime" });

  const entropy = features.entropy || 0;
  if (entropy > 0.7) evidence.push({ factor: "High Entropy", type: "bearish", strength: 0.4, description: "Noisy, unpredictable price action", source: "regime" });

  // ── GARCH evidence ──────────────────────────────────────────
  const garchSigma = features.garch_sigma;
  if (garchSigma !== undefined) {
    const volRegime = features.garch_vol_regime ?? 1;
    if (volRegime === 2) evidence.push({ factor: "EGARCH High Vol Regime", type: "bearish", strength: 0.6, description: `Elevated volatility forecast (σ=${garchSigma.toFixed(4)}) — whipsaw risk`, source: "volatility" });
    else if (volRegime === 0) evidence.push({ factor: "EGARCH Low Vol Regime", type: "bullish", strength: 0.4, description: `Compressed volatility (σ=${garchSigma.toFixed(4)}) — breakout potential building`, source: "volatility" });
  }
  const meanRevert = features.garch_mean_revert_signal;
  if (meanRevert !== undefined && meanRevert > 0.5) {
    evidence.push({ factor: "Strong Mean-Reversion Signal", type: "neutral", strength: 0.5, description: `EGARCH mean-reversion probability ${(meanRevert * 100).toFixed(0)}% — vol likely compressing`, source: "volatility" });
  }

  // ── Session evidence ────────────────────────────────────────
  if (features.session_is_peak === 1.0) {
    evidence.push({ factor: "Peak Trading Window", type: "bullish", strength: 0.4, description: "Current hour is in the top 25% for volatility — optimal entry timing", source: "volatility" });
  } else if (features.session_quality !== undefined && features.session_quality < 0.3) {
    evidence.push({ factor: "Low Session Quality", type: "bearish", strength: 0.3, description: "Outside optimal trading hours — reduced opportunity", source: "volatility" });
  }

  const bullish = evidence.filter(e => e.type === "bullish").sort((a, b) => b.strength - a.strength);
  const bearish = evidence.filter(e => e.type === "bearish").sort((a, b) => b.strength - a.strength);
  const neutral = evidence.filter(e => e.type === "neutral").sort((a, b) => b.strength - a.strength);

  const bullishScore = bullish.reduce((sum, e) => sum + e.strength, 0);
  const bearishScore = bearish.reduce((sum, e) => sum + e.strength, 0);
  const netScore = Math.max(-1, Math.min(1, (bullishScore - bearishScore) / Math.max(bullishScore + bearishScore, 1)));

  return {
    bullish,
    bearish,
    neutral,
    net_score: netScore,
  };
}

function _computeTrendDirection(call: any, features: Record<string, number>, structure: Record<string, number>): string {
    const biasTf = (features as any).bias_structure_bias;
    const setupTf = (features as any).setup_structure_bias;
    const confTf = (features as any).confirmation_structure_bias;
    const execSb = (features as any).structure_bias || 0;

    const biases = [biasTf, setupTf, confTf, execSb].filter((v: any) => typeof v === "number");
    if (biases.length === 0) return "neutral (insufficient data)";

    const bullish = biases.filter((v: number) => v > 0.1).length;
    const bearish = biases.filter((v: number) => v < -0.1).length;
    const total = biases.length;

    if (bullish === total) return "Bullish (full multi-TF alignment)";
    if (bearish === total) return "Bearish (full multi-TF alignment)";
    if (bullish >= bearish + 2) return "Bullish (from multi-TF analysis)";
    if (bearish >= bullish + 2) return "Bearish (from multi-TF analysis)";
    if (bullish > bearish) return "Moderately Bullish";
    if (bearish > bullish) return "Moderately Bearish";
    return "Neutral (mixed multi-TF signals)";
}

function buildRealTfRow(
    timeframe: string,
    features: Record<string, number>,
    prefix: string,
    confidence: number,
    structure: Record<string, number>,
    call: any,
): any {
    const sb = (features as any)[`${prefix}structure_bias`] ?? (features as any).structure_bias ?? 0;
    const regime = (features as any)[`${prefix}regime_trend_up`] ? "trend_up"
        : (features as any)[`${prefix}regime_trend_down`] ? "trend_down"
        : (features as any)[`${prefix}regime_range`] ? "range"
        : (features as any)[`${prefix}regime_volatile`] ? "volatile"
        : (features as any)[`${prefix}regime_compression`] ? "compression"
        : (features as any)[`${prefix}regime_unknown`] ? "unknown"
        : call.regime || "unknown";

    const dir = sb > 0.1 ? "bullish" : sb < -0.1 ? "bearish" : "neutral";

    return {
        timeframe,
        regime,
        structure_bias: sb,
        bos_up: (features as any)[`${prefix}bos_up`] ?? features.bos_up ?? 0,
        bos_down: (features as any)[`${prefix}bos_down`] ?? features.bos_down ?? 0,
        liquidity_sweep_up: (features as any)[`${prefix}liquidity_sweep_up`] ?? features.liquidity_sweep_up ?? 0,
        liquidity_sweep_down: (features as any)[`${prefix}liquidity_sweep_down`] ?? features.liquidity_sweep_down ?? 0,
        fvg_bullish_active: (features as any)[`${prefix}fvg_bullish_active`] ?? features.fvg_bullish_active ?? 0,
        fvg_bearish_active: (features as any)[`${prefix}fvg_bearish_active`] ?? features.fvg_bearish_active ?? 0,
        displacement_atr: (features as any)[`${prefix}displacement_atr`] ?? features.displacement_atr ?? 0,
        structure_bias_dup: sb,
        confidence,
        direction_bias: dir,
        key_levels: {
            recent_high: (features as any)[`${prefix}recent_swing_high`] ?? structure.recent_swing_high ?? 0,
            recent_low: (features as any)[`${prefix}recent_swing_low`] ?? structure.recent_swing_low ?? 0,
            invalidation: call.thesis_invalidation,
            target: call.primary_target,
        },
    };
}

function _computeDynamicCounterEvidence(
    call: any,
    features: Record<string, number>,
    regime: string,
): Array<{ name: string; description: string; strength: number; source: string }> {
    const counterEvidence: Array<{ name: string; description: string; strength: number; source: string }> = [];
    const direction = call.direction_bias;

    if (features.atr_ratio && features.atr_ratio > 1.5) {
        counterEvidence.push({ name: "High Volatility", description: `Expanded volatility (ATR ratio: ${features.atr_ratio.toFixed(1)}) increases risk`, strength: 0.6, source: "volatility" });
    }
    if (features.entropy && features.entropy > 0.7) {
        counterEvidence.push({ name: "High Entropy", description: "Noisy, unpredictable price action increased uncertainty", strength: 0.5, source: "regime" });
    }
    if (regime === "volatile") {
        counterEvidence.push({ name: "Volatile Regime", description: "Market in high volatility state — whipsaw risk elevated", strength: 0.5, source: "regime" });
    }
    if (regime === "range") {
        counterEvidence.push({ name: "Range-bound Market", description: "Mean-reverting environment without clear trend direction", strength: 0.5, source: "regime" });
    }
    if (regime === "compression") {
        counterEvidence.push({ name: "Compression Regime", description: "Low volatility suggests breakout is due — direction uncertain", strength: 0.4, source: "regime" });
    }

    const sb = features.structure_bias ?? 0;
    const htfSb = features.htf_structure_bias;
    if (direction === "buy" && sb < -0.1) {
        counterEvidence.push({ name: "Structure Contradiction", description: "Local structure bias is bearish while call direction is bullish", strength: 0.7, source: "structure" });
    }
    if (direction === "sell" && sb > 0.1) {
        counterEvidence.push({ name: "Structure Contradiction", description: "Local structure bias is bullish while call direction is bearish", strength: 0.7, source: "structure" });
    }
    if (typeof htfSb === "number" && Math.sign(sb) !== Math.sign(htfSb) && Math.abs(sb) > 0.1 && Math.abs(htfSb) > 0.1) {
        counterEvidence.push({ name: "Multi-TF Divergence", description: `Primary TF bias (${sb.toFixed(2)}) diverges from higher TF bias (${htfSb.toFixed(2)})`, strength: 0.6, source: "confluence" });
    }
    if (direction === "buy" && features.bos_down > 0) {
        counterEvidence.push({ name: "Bearish BOS Active", description: "Break of structure to the downside contradicts bullish thesis", strength: 0.7, source: "structure" });
    }
    if (direction === "sell" && features.bos_up > 0) {
        counterEvidence.push({ name: "Bullish BOS Active", description: "Break of structure to the upside contradicts bearish thesis", strength: 0.7, source: "structure" });
    }
    if (direction === "buy" && features.liquidity_sweep_up > 0) {
        counterEvidence.push({ name: "Upside Liquidity Sweep", description: "Price swept above highs and rejected — resistance remains", strength: 0.5, source: "structure" });
    }
    if (direction === "sell" && features.liquidity_sweep_down > 0) {
        counterEvidence.push({ name: "Downside Liquidity Sweep", description: "Price swept below lows and reclaimed — support remains", strength: 0.5, source: "structure" });
    }
    if (features.hurst_exponent && features.hurst_exponent < 0.4) {
        counterEvidence.push({ name: "Mean Reversion Signal", description: `Hurst exponent (${features.hurst_exponent.toFixed(2)}) suggests mean reversion likely`, strength: 0.45, source: "regime" });
    }

    return counterEvidence;
}

function buildMarketThesis(call: any) {
  const features = call.raw_features || {};
  const direction = call.direction_bias || "none";
  const confidence = call.confidence || 0.5;
  const regime = call.regime || "unknown";
  const tradeStatus = call.trade_status || "not_valid";

  const isBuy = direction === "buy";
  const isSell = direction === "sell";
  const thesisDirection = isBuy ? "bullish" : isSell ? "bearish" : "neutral";

  const thesisText = tradeStatus === "valid"
    ? (call.why || call.decision_summary || "Trade setup ready")
    : (call.why || "current movement is active but not a clean setup yet");

  const keyEvidence: Array<{ name: string; description: string; strength: number; source: string }> = [];
  if (features.bos_up) keyEvidence.push({ name: "Break of Structure Up", description: "Price broke above recent swing high", strength: 0.8, source: "structure" });
  if (features.bos_down) keyEvidence.push({ name: "Break of Structure Down", description: "Price broke below recent swing low", strength: 0.8, source: "structure" });
  if (features.fvg_bullish_active) keyEvidence.push({ name: "Bullish FVG Active", description: "Fair value gap being tested as support", strength: 0.6, source: "structure" });
  if (features.fvg_bearish_active) keyEvidence.push({ name: "Bearish FVG Active", description: "Fair value gap being tested as resistance", strength: 0.6, source: "structure" });
  if (features.liquidity_sweep_down) keyEvidence.push({ name: "Liquidity Sweep Down Reclaimed", description: "Price swept below lows then reclaimed", strength: 0.7, source: "structure" });
  if (features.liquidity_sweep_up) keyEvidence.push({ name: "Liquidity Sweep Up Rejected", description: "Price swept above highs then rejected", strength: 0.7, source: "structure" });
  if (regime === "trend_up") keyEvidence.push({ name: "Trending Up Regime", description: "Market in persistent uptrend", strength: 0.7, source: "regime" });
  else if (regime === "trend_down") keyEvidence.push({ name: "Trending Down Regime", description: "Market in persistent downtrend", strength: 0.7, source: "regime" });

  const counterEvidence = _computeDynamicCounterEvidence(call, features, regime);

  const sbFeatures = features.structure_bias ?? 0;
  const biasTfSb = (features as any).bias_structure_bias;
  const setupTfSb = (features as any).setup_structure_bias;
  const confTfSb = (features as any).confirmation_structure_bias;
  const biases = [biasTfSb, setupTfSb, confTfSb, sbFeatures].filter((v: any) => typeof v === "number");
  const alignedBiases = biases.filter((v: number) => Math.sign(v) === Math.sign(sbFeatures) && Math.abs(v) > 0.05).length;

  let timeframeAlignment: "full" | "partial" | "none" = "none";
  if (alignedBiases === biases.length && biases.length >= 3) {
    timeframeAlignment = "full";
  } else if (alignedBiases >= 2) {
    timeframeAlignment = "partial";
  }

  const thesisStructure = call.snapshot_structure || {};
  const thesisSwingHigh = thesisStructure.recent_swing_high || 0;
  const thesisSwingLow = thesisStructure.recent_swing_low || 0;
  const thesisHasRange = thesisSwingHigh > 0 && thesisSwingLow > 0;

  let thesisInvalidationPrice = call.thesis_invalidation ?? null;
  let thesisPrimaryTarget = call.primary_target ?? null;
  let thesisExtendedTarget = call.extended_target ?? null;

  if (thesisHasRange && thesisInvalidationPrice == null) {
    if (sbFeatures > 0.1) {
      thesisInvalidationPrice = thesisSwingLow;
      thesisPrimaryTarget = thesisSwingHigh;
      thesisExtendedTarget = thesisSwingHigh + Math.abs(thesisSwingHigh - thesisSwingLow) * 0.5;
    } else if (sbFeatures < -0.1) {
      thesisInvalidationPrice = thesisSwingHigh;
      thesisPrimaryTarget = thesisSwingLow;
      thesisExtendedTarget = thesisSwingLow - Math.abs(thesisSwingHigh - thesisSwingLow) * 0.5;
    } else {
      thesisInvalidationPrice = thesisSwingLow;
      thesisPrimaryTarget = thesisSwingHigh;
      thesisExtendedTarget = thesisSwingHigh + Math.abs(thesisSwingHigh - thesisSwingLow) * 0.5;
    }
  }

  return {
    direction: thesisDirection,
    thesis: thesisText,
    invalidation_price: thesisInvalidationPrice,
    invalidation_reason: call.invalidates_if || "Structure breaks against thesis",
    primary_target: thesisPrimaryTarget,
    extended_target: thesisExtendedTarget,
    timeframe_alignment: timeframeAlignment,
    key_evidence: keyEvidence,
    counter_evidence: counterEvidence,
    confidence,
  };
}

function buildConfidenceBreakdown(call: any) {
  const features = call.raw_features || {};
  const modelLongProb = call.model_long_probability ?? 0.5;
  const directionBias = call.direction_bias;

  const modelComponent = directionBias === "buy" ? modelLongProb : directionBias === "sell" ? 1 - modelLongProb : modelLongProb;
  const sb = features.structure_bias ?? 0;
  const structureComponent = directionBias === "buy"
    ? (sb > 0 ? 0.85 : sb > -0.2 ? 0.50 + (sb + 0.2) * 0.25 / 0.2 : 0.20)
    : directionBias === "sell"
      ? (sb < 0 ? 0.85 : sb < 0.2 ? 0.50 + (-sb + 0.2) * 0.25 / 0.2 : 0.20)
      : 0.5;

  const regime = call.regime || "unknown";
  const hurst = features.hurst_exponent ?? 0.5;
  const displacement = features.displacement_atr ?? 0;
  let regimeComponent = 0.5;
  if (regime === "trend_up") regimeComponent = directionBias === "buy" ? 0.85 : 0.20;
  else if (regime === "trend_down") regimeComponent = directionBias === "sell" ? 0.85 : 0.20;
  else if (regime === "volatile") regimeComponent = Math.abs(displacement) > 1.0 ? 0.65 : 0.35;
  else if (regime === "compression") regimeComponent = 0.45;
  else if (regime === "range") regimeComponent = 0.55;

  const slope = features.slope_20_atr ?? 0;
  const momentumComponent = directionBias === "buy"
    ? Math.max(0, Math.min(1, slope * 0.5 + (features.ema_9_21_spread_atr ?? 0) * 0.3))
    : directionBias === "sell"
      ? Math.max(0, Math.min(1, -slope * 0.5 - (features.ema_9_21_spread_atr ?? 0) * 0.3))
      : 0.5;

  const atrRatio = features.atr_ratio ?? 1.0;
  const volatilityComponent = atrRatio > 1.5 ? 0.40 : atrRatio < 0.7 ? 0.60 : 0.55;

  const calibratedProb = call.confidence ?? modelLongProb;

  // Compute GARCH and session components for the weighted sum
  // GARCH: high mean-reversion + directional bias = LOWER confidence
  // (price likely to revert against the trade). Low vol = breakout potential.
  const garchComponent = (() => {
    const garchSigma = features.garch_sigma;
    const meanRevert = features.garch_mean_revert_signal ?? 0;
    const volRegime = features.garch_vol_regime ?? 1;
    if (garchSigma === undefined) return 0.5;
    let score = 0.5;
    // Mean reversion working AGAINST a directional trade
    if (meanRevert > 0.5 && directionBias !== "none") score -= 0.15;
    // Mean reversion favorable when flat (no directional risk)
    if (meanRevert > 0.5 && directionBias === "none") score += 0.10;
    if (volRegime === 0) score += 0.10; // low vol = breakout potential
    if (volRegime === 2) score -= 0.15; // high vol = whipsaw risk
    return Math.max(0, Math.min(1, score));
  })();

  const sessionComponent = (() => {
    const sq = features.session_quality;
    if (sq === undefined) return 0.5;
    return sq;
  })();

  // Weighted sum using ALL components (including new GARCH + session)
  const w = {
    model: 0.03, structure: 0.25, regime: 0.18,
    mean_reversion: 0.08, displacement: 0.10, momentum: 0.08,
    volatility: 0.06, garch: 0.12, session: 0.05, confluence: 0.05,
  };
  const weightedFinal = (
    w.model * modelComponent
    + w.structure * structureComponent
    + w.regime * regimeComponent
    + w.mean_reversion * ((features.position_in_20_range ?? 0.5) * 0.4 + 0.3)
    + w.displacement * Math.min(1, Math.abs(displacement) / 2.5)
    + w.momentum * momentumComponent
    + w.volatility * volatilityComponent
    + w.garch * garchComponent
    + w.session * sessionComponent
    + w.confluence * 0.5
  );

  return {
    model: modelLongProb,
    structure: structureComponent,
    regime: regimeComponent,
    mean_reversion: (features.position_in_20_range ?? 0.5) * 0.4 + 0.3,
    displacement: Math.min(1, Math.abs(displacement) / 2.5),
    momentum: momentumComponent,
    volatility: volatilityComponent,
    garch: garchComponent,
    session: sessionComponent,
    confluence: 0.5,
    weights: w,
    calibrated: calibratedProb,
    final: weightedFinal,
  };
}

function buildConfidenceTrend(history: any[]) {
  const points = history.slice(-20).reverse().map((call: any) => ({
    timestamp: call.generated_at,
    confidence: call.confidence || 0,
    calibrated_confidence: call.confidence || 0,
    direction_bias: call.direction_bias,
    regime: call.regime,
  }));

  const recent = points.slice(0, 5);
  const older = points.slice(5, 10);
  const recentAvg = recent.reduce((sum, p) => sum + p.confidence, 0) / Math.max(recent.length, 1);
  const olderAvg = older.reduce((sum, p) => sum + p.confidence, 0) / Math.max(older.length, 1);

  let trend: "improving" | "stable" | "degrading" = "stable";
  if (recentAvg > olderAvg + 0.05) trend = "improving";
  else if (recentAvg < olderAvg - 0.05) trend = "degrading";

  const allConf = points.map(p => p.confidence);
  const mean = allConf.reduce((a, b) => a + b, 0) / allConf.length;
  const variance = allConf.reduce((sum, c) => sum + Math.pow(c - mean, 2), 0) / allConf.length;
  const volatility = Math.sqrt(variance);

  return { history: points, trend, volatility };
}

function buildTradePlan(call: any) {
  const direction = call.direction_bias === "buy" ? "long" : call.direction_bias === "sell" ? "short" : "neutral";
  const entry = call.entry || call.current_close;
  const stop = call.execution_stop || call.stop_loss || call.thesis_invalidation;
  
  return {
    direction,
    entry: entry || null,
    executionStop: stop || null,
    thesisInvalidation: call.thesis_invalidation || null,
    primaryTarget: call.primary_target || call.take_profit || null,
    extendedTarget: call.extended_target || null,
    holdHorizonMinutes: call.hold_horizon_minutes || 60,
    rewardRisk: call.reward_risk || null,
    triggerType: call.execution_trigger_type || "awaiting_confirmation",
    tradeStatus: call.trade_status || "not_valid",
    executionLevels: {
      entry: entry || null,
      executionStop: stop || null,
      primaryTarget: call.primary_target || call.take_profit || null,
      extendedTarget: call.extended_target || null,
      thesisInvalidation: call.thesis_invalidation || null,
    },
    thesis: call.why || call.decision_summary || call.briefing || "Market analysis in progress",
    invalidationReason: call.invalidates_if || call.why || "Setup conditions not yet met",
  };
}

function buildAlternativeScenario(call: any) {
  const direction = call.direction_bias;
  const confidence = call.confidence || 0.5;
  const regime = call.regime || "unknown";

  if (call.trade_status === "valid") {
    const opposite = direction === "buy" ? "short" : "long";
    return {
      scenario: `Market reverses to ${opposite}`,
      probability: 1 - confidence,
      description: `If the ${direction === "buy" ? "bullish" : "bearish"} thesis is wrong, price may reverse to ${call.thesis_invalidation || "invalidation level"}`,
      what_would_change: `Direction would flip to ${opposite}, thesis invalidated at ${call.thesis_invalidation || "unknown level"}`,
      trigger_condition: `Price closes beyond ${call.thesis_invalidation || "thesis invalidation level"}`,
    };
  }

  // For stand_aside: provide context-aware alternative scenario
  if (regime === "range") {
    return {
      scenario: "Range continues with false breakouts",
      probability: 0.6,
      description: "Market remains in consolidation; breakout attempts likely fail",
      what_would_change: "Price chops within range boundaries",
      trigger_condition: "Price closes outside range extremes with volume",
    };
  }

  if (regime === "trend_up" || regime === "trend_down") {
    const trend = regime === "trend_up" ? "uptrend" : "downtrend";
    return {
      scenario: `Trend continuation in ${trend}`,
      probability: 0.55,
      description: `Market structure supports continued ${trend}; pullbacks are buying/selling opportunities`,
      what_would_change: "Trend structure breaks with lower highs/higher lows",
      trigger_condition: "Structure breaks against trend direction",
    };
  }

  return {
    scenario: "Directional bias emerges",
    probability: 0.5,
    description: "Market structure unclear; waiting for directional commitment",
    what_would_change: "Clear BOS/FVG/liquidity sweep defines next move",
    trigger_condition: "Break of structure or fair value gap formation",
  };
}

function buildTradeProgress(call: any, history: any[]) {
  const events = [];

  events.push({
    timestamp: call.generated_at,
    type: "call_generated",
    description: `${call.call} generated with ${(call.confidence || 0) * 100}% confidence`,
    price: call.current_close,
    guardian_state: call.guardian_state,
    confidence: call.confidence,
  });

  events.push({
    timestamp: new Date().toISOString(),
    type: "guardian_update",
    description: `Guardian state: ${call.guardian_state}`,
    price: call.current_close,
    guardian_state: call.guardian_state,
    confidence: call.confidence,
  });

  return { events, current_phase: call.guardian_state, time_in_phase: null };
}

function buildRiskAssessment(call: any, propProfile: any) {
  const riskState = call.risk_state || {};

  return {
    risk_per_trade: 0.5,
    max_daily_loss: (riskState.max_daily_loss_fraction || 0.02) * 100,
    max_consecutive_losses: riskState.max_consecutive_losses || 4,
    current_daily_pnl: riskState.realized_pnl ?? 0,
    consecutive_losses: riskState.consecutive_losses ?? 0,
    open_positions: riskState.open_positions ?? 0,
    max_open_positions: riskState.max_open_positions ?? 1,
    current_drawdown: riskState.daily_drawdown_pct ?? 0,
    max_drawdown_limit: (riskState.max_daily_loss_fraction || 0.02) * 100,
    risk_reward_ratio: call.reward_risk || 0,
    position_size: 0.01,
    max_position_size: 0.1,
    trades_today: riskState.trades_today ?? 0,
    equity: riskState.equity ?? 1000,
  };
}

function buildThesisInvalidation(call: any) {
  const features = call.raw_features || {};
  const structure = call.snapshot_structure || {};
  const sb = features.structure_bias || 0;
  const swingHigh = structure.recent_swing_high || 0;
  const swingLow = structure.recent_swing_low || 0;
  const hasSwingRange = swingHigh > 0 && swingLow > 0;
  const rangeWidth = hasSwingRange ? Math.abs(swingHigh - swingLow) : 0;

  let invalidation = call.thesis_invalidation ?? null;

  if (hasSwingRange && invalidation == null) {
    if (sb > 0.1) {
      invalidation = swingLow;
    } else if (sb < -0.1) {
      invalidation = swingHigh;
    } else {
      invalidation = swingLow;
    }
  }

  return {
    level: invalidation || 0,
    reason: "Price invalidates the structural thesis",
    distance_from_current: invalidation ? Math.abs(invalidation - (call.current_close || 0)) : 0,
    distance_in_atr: 0,
    time_since_signal: 0,
    invalidation_triggers: [
      `Close beyond ${invalidation || "invalidation level"}`,
      "Structure breaks against thesis",
      "Regime shifts against bias",
    ],
  };
}

function buildAINarrative(call: any) {
  const features = call.raw_features || {};
  const directionBias = call.direction_bias;
  const regime = call.regime || "unknown";
  const sb = features.structure_bias ?? 0;
  const conf = call.confidence || 0.5;
  const structDirection = directionBias === "buy" ? "bullish" : directionBias === "sell" ? "bearish" : "neutral";

  const structSummary = sb > 0.3
    ? "strongly bullish with breaks of structure to the upside"
    : sb < -0.3
    ? "strongly bearish with breaks of structure to the downside"
    : sb > 0
    ? "mildly bullish"
    : sb < 0
    ? "mildly bearish"
    : "neutral / mixed";

  const keyDrivers = [];
  if (features.bos_up) keyDrivers.push("Bullish break of structure above swing highs");
  if (features.bos_down) keyDrivers.push("Bearish break of structure below swing lows");
  if (features.fvg_bullish_active) keyDrivers.push("Active bullish fair value gap supporting price");
  if (features.fvg_bearish_active) keyDrivers.push("Active bearish fair value gap resisting price");
  if (features.liquidity_sweep_down) keyDrivers.push("Downside liquidity sweep reclaimed (bullish)");
  if (features.liquidity_sweep_up) keyDrivers.push("Upside liquidity sweep rejected (bearish)");
  const displacementAtR = features.displacement_atr ?? 0;
  if (Math.abs(displacementAtR) > 1.0) keyDrivers.push(`Strong displacement (${displacementAtR.toFixed(1)} ATR)`);
  if (regime === "trend_up") keyDrivers.push("Market in uptrend regime");
  else if (regime === "trend_down") keyDrivers.push("Market in downtrend regime");
  // GARCH-driven insights
  const garchSigma = features.garch_sigma;
  if (garchSigma !== undefined) {
    const volRegime = features.garch_vol_regime ?? 1;
    if (volRegime === 2) keyDrivers.push(`EGARCH detects elevated volatility (σ=${garchSigma.toFixed(4)})`);
    else if (volRegime === 0) keyDrivers.push(`EGARCH detects low volatility — breakout potential building (σ=${garchSigma.toFixed(4)})`);
  }
  const meanRevert = features.garch_mean_revert_signal;
  if (meanRevert !== undefined && meanRevert > 0.5) {
    keyDrivers.push(`Strong mean-reversion signal (${(meanRevert * 100).toFixed(0)}%) — vol likely compressing`);
  }
  // Session insights
  const isPeak = features.session_is_peak === 1.0;
  if (isPeak) keyDrivers.push("Peak volatility window — optimal entry timing");
  if (keyDrivers.length === 0) keyDrivers.push("Structure signals are neutral — no dominant direction");

  const uncertainties = [];
  if ((features.atr_ratio ?? 0) > 1.5) uncertainties.push("Elevated volatility increases whipsaw risk");
  if ((features.entropy ?? 0) > 0.7) uncertainties.push("High entropy = noisy, unpredictable price action");
  if (regime === "volatile") uncertainties.push("Volatile regime — price can move abruptly");
  if (regime === "range") uncertainties.push("Range-bound market can trap breakout trades");
  if ((features.garch_persistence ?? 0.96) > 0.97) uncertainties.push("High GARCH persistence — regime shift may take longer to materialize");
  if (features.session_is_peak !== 1.0 && features.session_quality !== undefined && features.session_quality < 0.4) uncertainties.push("Low session quality — outside optimal trading hours");
  if (call.trade_status !== "valid") uncertainties.push("No valid trade signal — thesis is unconfirmed");
  if (uncertainties.length === 0) uncertainties.push("Standard market risk applies");

  const directionLabel = directionBias === "buy" ? "long" : directionBias === "sell" ? "short" : "flat";
  const baseCase = call.trade_status === "valid"
    ? `${call.symbol} ${directionLabel} trade plays out as structured, hitting primary target`
    : `${call.symbol} remains in ${regime.replace("_", " ")} regime without clean entry`;
  const bullCase = directionBias !== "sell"
    ? `Bullish momentum accelerates; structure extends to new highs`
    : `Bearish thesis fails; aggressive reversal breaks structure upward`;
  const bearCase = directionBias !== "buy"
    ? `Bearish momentum accelerates; structure extends to new lows`
    : `Bullish thesis fails; aggressive reversal breaks structure downward`;

  return {
    summary: `${call.symbol} ${structDirection} assessment in ${regime.replace("_", " ")} regime with ${(conf * 100).toFixed(0)}% confidence`,
    market_context: `${call.symbol} is in a ${regime.replace("_", " ")} regime. Structural analysis shows ${structSummary} conditions.`,
    thesis: call.why || call.decision_summary || "Thesis derived from real-time market structure analysis",
    key_drivers: keyDrivers,
    uncertainties,
    scenario_analysis: {
      base_case: baseCase,
      bull_case: bullCase,
      bear_case: bearCase,
    },
    recommendation: call.trade_status === "valid"
      ? `Consider ${directionLabel} entry with strict risk controls`
      : call.wait_for || "Wait for a clean directional setup before entering",
    confidence_rationale: conf > 0.55
      ? "Confidence supported by structural signals and regime alignment"
      : conf > 0.45
      ? "Confidence near threshold — exercise caution"
      : "Confidence below actionable threshold — wait for stronger signals",
  };
}

function buildDecisionHistory(history: any[]) {
  return (history || []).slice(0, 20).map((call: any) => ({
    timestamp: call.generated_at,
    symbol: call.symbol,
    call: call.call,
    trade_status: call.trade_status,
    confidence: call.confidence,
    regime: call.regime,
    direction_bias: call.direction_bias,
    outcome: null,
    confidence_at_entry: call.confidence,
    pnl: null,
    call_age_seconds: call.call_age_seconds,
  }));
}

function buildPostTradeLearning(history: any[]) {
  if (!history || history.length === 0) return null;

  return {
    total_trades: history.length,
    win_rate: 0,
    avg_r_multiple: 0,
    profit_factor: 0,
    avg_hold_time: 0,
    best_setup: "pending_scoring",
    worst_setup: "pending_scoring",
    regime_performance: {},
    recent_insights: ["Run calibration scoring to populate trade outcomes."],
    calibration_quality: 0,
    model_version: "v1",
  };
}

// ── GARCH Volatility Forecast ──────────────────────────────────────
// Extracts EGARCH(1,1) features from raw_features.  These are the ONE
// genuinely exploitable property of synthetic indices — their variance
// clusters due to the generator's scheduling algorithm.

function buildGarchForecast(call: any) {
  const features = call.raw_features || {};
  const garchSigma = features.garch_sigma;
  if (garchSigma === undefined || garchSigma === null) return null;

  const volRegime = features.garch_vol_regime ?? 1.0;
  const volRegimeLabel = volRegime === 0 ? "low" : volRegime === 2 ? "high" : "normal";
  const meanRevert = features.garch_mean_revert_signal ?? 0.0;
  const zScore = features.garch_z_score ?? 0.0;
  const persistence = features.garch_persistence ?? 0.96;
  const halfLife = features.garch_half_life ?? 999.0;
  const longRunVol = features.garch_long_run_vol ?? garchSigma;
  const volRatio = features.garch_vol_ratio ?? 1.0;

  // Interpret the GARCH z-score for the user
  let zScoreInterpretation = "normal";
  if (Math.abs(zScore) > 3.0) zScoreInterpretation = "extreme — strong mean-reversion likely";
  else if (Math.abs(zScore) > 2.0) zScoreInterpretation = "elevated — vol likely to compress";
  else if (Math.abs(zScore) > 1.5) zScoreInterpretation = "moderately high";

  // Persistence interpretation
  let persistenceLabel = "high — regime changes slowly";
  if (persistence < 0.85) persistenceLabel = "low — rapid mean-reversion expected";
  else if (persistence < 0.93) persistenceLabel = "moderate";

  return {
    sigma: garchSigma,
    sigma_annualized: features.garch_sigma_annualized ?? garchSigma * Math.sqrt(252 * 24 * 4),
    forecast_variance: features.garch_forecast ?? garchSigma * garchSigma,
    vol_regime: volRegimeLabel,
    vol_ratio: volRatio,
    z_score: zScore,
    z_score_interpretation: zScoreInterpretation,
    mean_revert_signal: meanRevert,
    persistence: persistence,
    persistence_label: persistenceLabel,
    half_life: halfLife,
    long_run_vol: longRunVol,
    alpha: features.garch_alpha ?? 0.08,
    gamma: features.garch_gamma ?? -0.04,
    // Actionable insight for the user
    actionable: meanRevert > 0.6
      ? `Strong mean-reversion signal (${(meanRevert * 100).toFixed(0)}%) — vol likely compressing soon`
      : meanRevert > 0.3
      ? `Moderate mean-reversion signal (${(meanRevert * 100).toFixed(0)}%) — watch for vol compression`
      : volRegimeLabel === "high"
      ? `High volatility regime — ${persistenceLabel}`
      : volRegimeLabel === "low"
      ? `Low volatility regime — potential breakout building`
      : `Volatility normal — monitoring for regime shifts`,
  };
}

// ── Session Quality ────────────────────────────────────────────────
// Tracks which hours produce the most volatile moves.  The generator's
// server load balancing creates time-dependent behavior that is
// exploitable for timing entries.

function buildSessionQuality(call: any) {
  const features = call.raw_features || {};
  const sessionQuality = features.session_quality;
  if (sessionQuality === undefined || sessionQuality === null) return null;

  const volRank = features.session_vol_rank ?? 0.5;
  const isPeak = features.session_is_peak === 1.0;
  const hour = features.session_hour ?? 0;
  const trend = features.session_trend ?? 0.0;
  const consistency = features.session_consistency ?? 0.5;
  const totalHours = features.session_total_hours ?? 0;
  const totalObs = features.session_total_observations ?? 0;

  let qualityLabel = "average";
  if (sessionQuality >= 0.7) qualityLabel = "excellent";
  else if (sessionQuality >= 0.6) qualityLabel = "good";
  else if (sessionQuality <= 0.3) qualityLabel = "poor";

  let trendLabel = "stable";
  if (trend > 0.2) trendLabel = "increasing";
  else if (trend < -0.2) trendLabel = "decreasing";

  const hourStr = `${String(Math.floor(hour)).padStart(2, "0")}:00 UTC`;

  return {
    quality: sessionQuality,
    quality_label: qualityLabel,
    vol_rank: volRank,
    is_peak_hour: isPeak,
    hour: Math.floor(hour),
    hour_display: hourStr,
    trend: trend,
    trend_label: trendLabel,
    consistency: consistency,
    total_hours_tracked: totalHours,
    total_observations: totalObs,
    actionable: isPeak
      ? `Peak volatility window (${hourStr}) — best time for entries`
      : sessionQuality >= 0.6
      ? `Good session quality (${hourStr}) — acceptable for entries`
      : sessionQuality <= 0.3
      ? `Low volatility hour (${hourStr}) — consider waiting for better window`
      : `Average session quality (${hourStr})`,
  };
}

// ── Generator Fingerprint ──────────────────────────────────────────
// Detects which index is being traded by analyzing return statistics.
// Useful for confirming the system is connected to the right symbol.

function buildGeneratorFingerprint(call: any) {
  const features = call.raw_features || {};
  const detectedIndex = features.fp_detected_index;
  if (detectedIndex === undefined || detectedIndex === null) return null;

  const confidence = features.fp_confidence ?? 0.0;
  const kurtosis = features.fp_kurtosis ?? 0.0;
  const skewness = features.fp_skewness ?? 0.0;
  const clusterScore = features.fp_cluster_score ?? 0.0;

  const indexLabels: Record<number, string> = {
    0: "Volatility 10 (R_10)",
    1: "Volatility 25 (R_25)",
    2: "Volatility 50 (R_50)",
    3: "Volatility 75 (R_75)",
    4: "Volatility 100 (R_100)",
    5: "Boom 1000",
    6: "Crash 1000",
    7: "Boom 500",
    8: "Crash 500",
    9: "Boom 300",
    10: "Crash 300",
    11: "Step Index",
  };

  const label = indexLabels[Math.floor(detectedIndex)] ?? `Unknown (${detectedIndex})`;

  return {
    detected_index: Math.floor(detectedIndex),
    detected_label: label,
    confidence: confidence,
    kurtosis: kurtosis,
    skewness: skewness,
    cluster_score: clusterScore,
  };
}

// ── Missed Trade Learning ────────────────────────────────────────
// Reads resolved outcomes from data/missed_trade_outcomes.jsonl.
// Shows the engine's NO_TRADE history: what it predicted, what the
// market actually did, and whether it was a correct stay-out or a
// missed opportunity.  The range_miss_boost tracks how many missed
// opportunities have pushed the engine toward more aggressive range
// trading.

function buildMissedTradeLearning() {
  try {
    const engineRoot = process.env.SYNTHETIC_ENGINE_ROOT || process.cwd();
    const outcomesPath = join(engineRoot, "data", "missed_trade_outcomes.jsonl");
    const pendingPath = join(engineRoot, "data", "missed_trades.jsonl");

    let outcomes: any[] = [];
    let pending: any[] = [];

    if (existsSync(outcomesPath)) {
      try {
        const raw = readFileSync(outcomesPath, "utf-8");
        outcomes = raw
          .split("\n")
          .filter((l: string) => l.trim())
          .map((l: string) => { try { return JSON.parse(l); } catch { return null; } })
          .filter(Boolean)
          .slice(-20); // last 20 resolved trades
      } catch {
        // Read error — treat as empty
      }
    }

    if (existsSync(pendingPath)) {
      try {
        const raw = readFileSync(pendingPath, "utf-8");
        pending = raw
          .split("\n")
          .filter((l: string) => l.trim())
          .map((l: string) => { try { return JSON.parse(l); } catch { return null; } })
          .filter(Boolean);
      } catch {
        // Read error — treat as empty
      }
    }

    const totalResolved = outcomes.length;
    const missedOpportunities = outcomes.filter((o: any) => o.outcome === 1).length;
    const correctStayouts = outcomes.filter((o: any) => o.outcome === 0).length;
    const pendingCount = pending.length;
    const missRate = totalResolved > 0 ? missedOpportunities / totalResolved : 0;

    // Calculate the range_miss_boost: more missed opportunities = more aggressive in range
    // Caps at 0.3 (30% boost to range-bound confidence)
    const rangeMissBoost = Math.min(0.3, missRate * 0.5);

    // Recent outcomes with display-friendly formatting
    const recentOutcomes = outcomes.map((o: any) => ({
      symbol: o.symbol,
      recorded_at: o.recorded_at ? new Date(o.recorded_at * 1000).toISOString() : null,
      resolved_at: o.resolved_at ? new Date(o.resolved_at * 1000).toISOString() : null,
      model_prediction: o.model_long_probability > 0.5 ? "long" : o.model_long_probability < 0.5 ? "short" : "neutral",
      confidence_at_record: o.confidence,
      regime: o.regime,
      outcome: o.outcome === 1 ? "missed_opportunity" : "correct_stayout",
      price_at_record: o.current_price,
      price_at_resolution: o.resolved_price,
      price_move_atr: o.price_move_atr,
    })).reverse(); // newest first

    return {
      total_resolved: totalResolved,
      missed_opportunities: missedOpportunities,
      correct_stayouts: correctStayouts,
      miss_rate: missRate,
      miss_rate_display: `${(missRate * 100).toFixed(1)}%`,
      pending_count: pendingCount,
      range_miss_boost: rangeMissBoost,
      range_miss_boost_display: `${(rangeMissBoost * 100).toFixed(1)}%`,
      recent_outcomes: recentOutcomes,
      status: totalResolved === 0 ? "no_data" : "active",
      insight: totalResolved === 0
        ? "No resolved missed trades yet. The engine will start learning once NO_TRADE decisions are recorded and resolved."
        : missRate > 0.4
        ? `High miss rate (${(missRate * 100).toFixed(0)}%) — the engine has been overly cautious. Range-bound confidence boosted by ${(rangeMissBoost * 100).toFixed(0)}%.`
        : missRate > 0.2
        ? `Moderate miss rate (${(missRate * 100).toFixed(0)}%) — the engine is recalibrating. Range-bound confidence boosted by ${(rangeMissBoost * 100).toFixed(0)}%.`
        : `Low miss rate (${(missRate * 100).toFixed(0)}%) — the engine is well-calibrated.`,
    };
  } catch {
    return null;
  }
}
// ── Curve-Fitting Test ──────────────────────────────────────────
// Reads a cached synthetic backtest report from disk.  The report is
// generated by `python -m synthetic_trader backtest-synth --symbol R_100 --artifact-output data/curve_fitting_report.json`
// This function simply reads the cached JSON and returns it to the frontend.

function buildCurveFittingTest() {
  try {
    const engineRoot = process.env.SYNTHETIC_ENGINE_ROOT || process.cwd();
    const reportPath = join(engineRoot, "data", "curve_fitting_report.json");

    if (!existsSync(reportPath)) return null;

    const raw = readFileSync(reportPath, "utf-8");
    const report = JSON.parse(raw);

    // Extract the key fields the UI needs
    const aggregate = report.aggregate || {};
    const consistency = report.consistency || {};
    const curveFitting = report.curve_fitting || {};
    const propFirm = report.prop_firm || null;

    const episodes = Array.isArray(report.episodes)
      ? report.episodes.map((e: any) => ({
          episode: e.episode,
          seed: e.seed,
          trades: e.trades,
          win_rate: e.win_rate,
          profit_factor: e.profit_factor,
          expectancy_r: e.expectancy_r,
          net_pnl: e.net_pnl,
          signals: e.signals,
        }))
      : [];

    return {
      symbol: report.symbol || "unknown",
      n_episodes: report.n_episodes || 0,
      n_ticks_per_episode: report.n_ticks_per_episode || 0,
      aggregate: {
        mean_win_rate: aggregate.mean_win_rate ?? 0,
        mean_profit_factor: aggregate.mean_profit_factor ?? 0,
        mean_expectancy_r: aggregate.mean_expectancy_r ?? 0,
        mean_net_pnl: aggregate.mean_net_pnl ?? 0,
        mean_signals: aggregate.mean_signals ?? 0,
      },
      consistency: {
        win_rate_std: consistency.win_rate_std ?? 0,
        profit_factor_std: consistency.profit_factor_std ?? 0,
        consistency_score: consistency.consistency_score ?? 0,
      },
      curve_fitting: {
        deflated_sharpe: curveFitting.deflated_sharpe ?? 0,
        pbo_score: curveFitting.pbo_score ?? 0,
        monte_carlo_p_value: curveFitting.monte_carlo_p_value ?? 0,
        edge_detected: curveFitting.edge_detected ?? false,
      },
      prop_firm: propFirm ? {
        name: propFirm.name || "",
        total_breaches: propFirm.total_breaches ?? 0,
        daily_loss_breaches: propFirm.daily_loss_breaches ?? 0,
        drawdown_breaches: propFirm.drawdown_breaches ?? 0,
        risk_per_trade_breaches: propFirm.risk_per_trade_breaches ?? 0,
        breach_rate: propFirm.breach_rate ?? 0,
      } : null,
      verdict: report.verdict || "No test run yet",
      explanation: report.explanation || "Run the synthetic backtest to generate a curve-fitting report.",
      episodes,
      ran_at: report.ran_at || null,
    };
  } catch {
    return null;
  }
}
