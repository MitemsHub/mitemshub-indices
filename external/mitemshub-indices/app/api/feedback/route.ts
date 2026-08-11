import { NextResponse } from "next/server";
import { appendFile, readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join } from "node:path";

type SignalFeedback = {
  signal_id: string;
  symbol: string;
  direction: string;
  generated_at: string;
  entry: number;
  stop_loss: number;
  take_profit: number;
  confidence: number;
  regime: string;
  signal_strength: string;
  user_feedback: string | null;
  feedback_at: string | null;
  feedback_notes: string | null;
  outcome: string | null;
  outcome_price: number | null;
  outcome_at: string | null;
  pnl_pips: number | null;
  r_multiple: number | null;
  executed_at: string | null;
  fed_to_calibration: boolean;
  fed_at: string | null;
};

function getDataDir(): string {
  const engineRoot = process.env.SYNTHETIC_ENGINE_ROOT || process.cwd();
  return join(engineRoot, "data");
}

function getFeedbackPath(): string {
  return join(getDataDir(), "signal_feedback.jsonl");
}

function getOutcomesPath(): string {
  return join(getDataDir(), "signal_outcomes.jsonl");
}

async function readJsonl(path: string): Promise<SignalFeedback[]> {
  if (!existsSync(path)) return [];
  try {
    const content = await readFile(path, "utf8");
    return content
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => JSON.parse(line) as SignalFeedback);
  } catch {
    return [];
  }
}

function makeSignalId(symbol: string, generatedAt: string): string {
  return `${symbol}_${generatedAt.replace(/:/g, "-").replace(/\./g, "-")}`;
}

/** Read tick CSV tail and extract prices after a given epoch. */
async function readPricesAfter(
  symbol: string,
  afterEpochMs: number,
): Promise<number[]> {
  const engineRoot = process.env.SYNTHETIC_ENGINE_ROOT || process.cwd();
  const candidates = [
    join(engineRoot, "data", `${symbol}_ticks.csv`),
    join(engineRoot, "data", `${symbol.toLowerCase().replace(/_/g, "")}_ticks.csv`),
    join(engineRoot, "data", `${symbol.toUpperCase()}_ticks.csv`),
  ];
  const csvPath = candidates.find((p) => existsSync(p));
  if (!csvPath) return [];
  try {
    const content = await readFile(csvPath, "utf8");
    const lines = content.split("\n").filter((l) => l.trim());
    const prices: number[] = [];
    const afterSec = afterEpochMs / 1000;
    for (const line of lines) {
      const parts = line.split(",");
      if (parts.length < 3) continue;
      const epoch = parseFloat(parts[0]);
      const price = parseFloat(parts[2]);
      if (isNaN(epoch) || isNaN(price)) continue;
      if (epoch >= afterSec) prices.push(price);
    }
    return prices;
  } catch {
    return [];
  }
}

/** Resolve a trade outcome by checking TP/SL against CSV tick prices. */
async function resolveTradeOutcome(
  signal: SignalFeedback,
): Promise<{ label: string; exit_price: number | null; pnl_pips: number | null; r_multiple: number | null }> {
  const generatedAtMs = new Date(signal.generated_at).getTime();
  const prices = await readPricesAfter(signal.symbol, generatedAtMs);
  if (prices.length === 0) {
    return { label: "expired", exit_price: null, pnl_pips: null, r_multiple: null };
  }
  const stopDist = Math.abs(signal.entry - signal.stop_loss);
  if (stopDist <= 0) {
    return { label: "expired", exit_price: null, pnl_pips: null, r_multiple: null };
  }

  let hitTp = false;
  let hitSl = false;
  let exitPrice = prices[prices.length - 1];

  for (const price of prices) {
    if (signal.direction === "buy") {
      if (price >= signal.take_profit) { hitTp = true; exitPrice = price; break; }
      if (price <= signal.stop_loss) { hitSl = true; exitPrice = price; break; }
    } else {
      if (price <= signal.take_profit) { hitTp = true; exitPrice = price; break; }
      if (price >= signal.stop_loss) { hitSl = true; exitPrice = price; break; }
    }
  }

  if (hitTp && !hitSl) {
    const pnl = Math.abs(signal.take_profit - signal.entry);
    return { label: "tp_hit", exit_price: exitPrice, pnl_pips: pnl, r_multiple: pnl / stopDist };
  }
  if (hitSl) {
    const pnl = -Math.abs(signal.stop_loss - signal.entry);
    return { label: "sl_hit", exit_price: exitPrice, pnl_pips: pnl, r_multiple: -1 };
  }
  // Neither hit — check final P&L direction
  const finalPnl = signal.direction === "buy"
    ? exitPrice - signal.entry
    : signal.entry - exitPrice;
  return {
    label: finalPnl > 0 ? "manual_win" : finalPnl < 0 ? "manual_loss" : "expired",
    exit_price: exitPrice,
    pnl_pips: finalPnl,
    r_multiple: finalPnl / stopDist,
  };
}

/** Feed resolved outcomes into the Python calibration buffer. */
async function feedOutcomesToCalibration(
  outcomes: Array<{ signal_id: string; prediction: number; label: number }>,
): Promise<void> {
  const engineRoot = process.env.SYNTHETIC_ENGINE_ROOT || process.cwd();
  const outcomesPath = join(engineRoot, "data", "calibration_outcomes.jsonl");
  await mkdir(join(outcomesPath, ".."), { recursive: true });
  const lines = outcomes.map((o) => JSON.stringify({
    ...o,
    fed_at: new Date().toISOString(),
  }));
  await appendFile(outcomesPath, lines.join("\n") + "\n", "utf8");
}

/** GET /api/feedback — fetch signal feedback history */
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const symbol = searchParams.get("symbol");
  const limit = parseInt(searchParams.get("limit") || "50", 10);
  const pendingOnly = searchParams.get("pending") === "true";

  const signals = await readJsonl(getFeedbackPath());

  let filtered = signals;
  if (symbol) {
    filtered = filtered.filter((s) => s.symbol === symbol);
  }
  if (pendingOnly) {
    filtered = filtered.filter((s) => s.outcome !== null && s.user_feedback === null);
  }

  // Sort by generated_at descending, return most recent
  filtered.sort((a, b) => b.generated_at.localeCompare(a.generated_at));
  const sliced = filtered.slice(0, limit);

  // Compute stats
  const resolved = signals.filter((s) => s.outcome !== null);
  const tpHits = resolved.filter((s) => s.outcome === "tp_hit").length;
  const slHits = resolved.filter((s) => s.outcome === "sl_hit").length;
  const withFeedback = resolved.filter((s) => s.user_feedback !== null);
  const goodFeedback = withFeedback.filter((s) => s.user_feedback === "good").length;
  const badFeedback = withFeedback.filter((s) => s.user_feedback === "bad").length;

  return NextResponse.json({
    signals: sliced,
    stats: {
      total: signals.length,
      resolved: resolved.length,
      pending: signals.length - resolved.length,
      tp_hits: tpHits,
      sl_hits: slHits,
      win_rate: resolved.length > 0 ? tpHits / resolved.length : 0,
      with_feedback: withFeedback.length,
      good_feedback: goodFeedback,
      bad_feedback: badFeedback,
      pending_feedback: resolved.length - withFeedback.length,
    },
  });
}

/** POST /api/feedback — record feedback or a new signal */
export async function POST(request: Request) {
  const body = await request.json();
  const { action } = body;

  if (action === "record_signal") {
    // Record a new signal for tracking
    const signalId = makeSignalId(body.symbol, body.generated_at);
    const signal: SignalFeedback = {
      signal_id: signalId,
      symbol: body.symbol,
      direction: body.direction,
      generated_at: body.generated_at,
      entry: body.entry,
      stop_loss: body.stop_loss,
      take_profit: body.take_profit,
      confidence: body.confidence,
      regime: body.regime,
      signal_strength: body.signal_strength,
      user_feedback: null,
      feedback_at: null,
      feedback_notes: null,
      outcome: null,
      outcome_price: null,
      outcome_at: null,
      pnl_pips: null,
      r_multiple: null,
      executed_at: null,
      fed_to_calibration: false,
      fed_at: null,
    };

    const path = getFeedbackPath();
    await mkdir(join(path, ".."), { recursive: true });
    await appendFile(path, JSON.stringify(signal) + "\n", "utf8");

    return NextResponse.json({ success: true, signal_id: signalId });
  }

  if (action === "record_feedback") {
    // Record user feedback on a signal
    const { signal_id, feedback, notes } = body;
    if (!signal_id || !feedback) {
      return NextResponse.json({ error: "signal_id and feedback required" }, { status: 400 });
    }

    const signals = await readJsonl(getFeedbackPath());
    const signal = signals.find((s) => s.signal_id === signal_id);
    if (!signal) {
      return NextResponse.json({ error: "Signal not found" }, { status: 404 });
    }

    signal.user_feedback = feedback;
    signal.feedback_at = new Date().toISOString();
    signal.feedback_notes = notes || null;

    // Rewrite the file with updated signal
    const path = getFeedbackPath();
    await mkdir(join(path, ".."), { recursive: true });
    const content = signals.map((s) => JSON.stringify(s)).join("\n") + "\n";
    await writeFile(path, content, "utf8");

    return NextResponse.json({ success: true });
  }

  if (action === "record_execution") {
    // Mark a signal as executed by the user. Does NOT set outcome —
    // the outcome will be determined later by bulk_resolve after
    // the hold horizon expires.
    const { signal_id } = body;
    if (!signal_id) {
      return NextResponse.json({ error: "signal_id required" }, { status: 400 });
    }

    const signals = await readJsonl(getFeedbackPath());
    const signal = signals.find((s) => s.signal_id === signal_id);
    if (!signal) {
      return NextResponse.json({ error: "Signal not found" }, { status: 404 });
    }

    signal.executed_at = new Date().toISOString();

    // Rewrite the file
    const path = getFeedbackPath();
    await mkdir(join(path, ".."), { recursive: true });
    const content = signals.map((s) => JSON.stringify(s)).join("\n") + "\n";
    await writeFile(path, content, "utf8");

    return NextResponse.json({ success: true });
  }

  if (action === "record_outcome") {
    // Record outcome for a signal
    const { signal_id, outcome, outcome_price, pnl_pips, r_multiple } = body;
    if (!signal_id || !outcome) {
      return NextResponse.json({ error: "signal_id and outcome required" }, { status: 400 });
    }

    const signals = await readJsonl(getFeedbackPath());
    const signal = signals.find((s) => s.signal_id === signal_id);
    if (!signal) {
      return NextResponse.json({ error: "Signal not found" }, { status: 404 });
    }

    signal.outcome = outcome;
    signal.outcome_price = outcome_price || null;
    signal.outcome_at = new Date().toISOString();
    signal.pnl_pips = pnl_pips || null;
    signal.r_multiple = r_multiple || null;

    // Rewrite the file
    const path = getFeedbackPath();
    await mkdir(join(path, ".."), { recursive: true });
    const content = signals.map((s) => JSON.stringify(s)).join("\n") + "\n";
    await writeFile(path, content, "utf8");

    return NextResponse.json({ success: true });
  }

  if (action === "bulk_resolve") {
    // Auto-resolve signals that have passed their hold horizon.
    // Priority order:
    //   1. Executed trades (executed_at set) — check CSV for TP/SL hits
    //   2. Non-executed signals — check CSV for directional movement
    //   3. No price data — mark as expired
    const signals = await readJsonl(getFeedbackPath());
    let resolved = 0;
    const calibrationOutcomes: Array<{ signal_id: string; prediction: number; label: number }> = [];

    // Hold horizon: 6 hours for sniper mode (4-6 hour swing trades)
    const HOLD_MINUTES = 360;
    const now = Date.now();

    for (const signal of signals) {
      if (signal.outcome !== null) continue; // already resolved

      const generatedAt = new Date(signal.generated_at).getTime();
      const elapsed = (now - generatedAt) / (1000 * 60);

      if (elapsed < HOLD_MINUTES) continue; // not yet time to resolve

      // Resolve the outcome from CSV tick data
      const outcome = await resolveTradeOutcome(signal);
      signal.outcome = outcome.label;
      signal.outcome_price = outcome.exit_price;
      signal.pnl_pips = outcome.pnl_pips;
      signal.r_multiple = outcome.r_multiple;
      signal.outcome_at = new Date().toISOString();
      resolved++;

      // Feed real outcomes (tp_hit, sl_hit, manual_win, manual_loss) into calibration
      // These are genuine market outcomes that the model can learn from.
      if (outcome.label === "tp_hit" || outcome.label === "sl_hit" ||
          outcome.label === "manual_win" || outcome.label === "manual_loss") {
        const label = (outcome.label === "tp_hit" || outcome.label === "manual_win") ? 1 : 0;
        calibrationOutcomes.push({
          signal_id: signal.signal_id,
          prediction: signal.confidence,
          label,
        });
      }
    }

    if (resolved > 0) {
      const path = getFeedbackPath();
      await mkdir(join(path, ".."), { recursive: true });
      const content = signals.map((s) => JSON.stringify(s)).join("\n") + "\n";
      await writeFile(path, content, "utf8");
    }

    // Feed outcomes into Python calibration buffer
    if (calibrationOutcomes.length > 0) {
      await feedOutcomesToCalibration(calibrationOutcomes);
    }

    return NextResponse.json({
      success: true,
      resolved,
      calibration_fed: calibrationOutcomes.length,
      details: calibrationOutcomes.map((o) => ({
        signal_id: o.signal_id,
        label: o.label === 1 ? "win" : "loss",
        confidence: o.prediction,
      })),
    });
  }

  return NextResponse.json({ error: "Unknown action" }, { status: 400 });
}
