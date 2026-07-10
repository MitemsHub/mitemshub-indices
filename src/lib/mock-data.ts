import type { FreshCallResponse, PropProfileResponse } from "./contracts";
import type { PropAccountState } from "./prop-policy";

type SymbolCode = FreshCallResponse["symbol"];
type MockCallBase = Omit<
  FreshCallResponse,
  | "account_mode"
  | "prop_compliance"
  | "prop_adjusted_risk"
  | "prop_block_reason"
  | "prop_remaining_daily_buffer"
  | "prop_remaining_overall_buffer"
>;

const baseCalls: Record<SymbolCode, MockCallBase> = {
  R_75: {
    symbol: "R_75",
    call: "sell_candidate",
    alert_type: "setup_candidate",
    trade_status: "valid",
    confidence: 0.61,
    regime: "trend_down",
    direction_bias: "sell",
    why: "price is still leaning lower and sellers remain in control",
    wait_for: "wait for bearish continuation below resistance",
    decision_summary: "sell setup ready; price is still leaning lower and sellers remain in control",
    entry_area: "around 320123.4",
    stop_area: "above 321000.0",
    target_area: "toward 318600.0",
    entry: 320123.4,
    stop_loss: 321000.0,
    take_profit: 318600.0,
    reward_risk: 1.8,
    generated_at: "2026-07-09T12:05:00Z",
  },
  R_100: {
    symbol: "R_100",
    call: "buy_candidate",
    alert_type: "setup_candidate",
    trade_status: "valid",
    confidence: 0.66,
    regime: "trend_up",
    direction_bias: "buy",
    why: "buyers remain in control and the trend is still pointing upward",
    wait_for: "wait for a clean bullish continuation close",
    decision_summary:
      "buy setup ready; buyers remain in control and the trend is still pointing upward",
    entry_area: "around 51234.6",
    stop_area: "below 51188.2",
    target_area: "toward 51326.4",
    entry: 51234.6,
    stop_loss: 51188.2,
    take_profit: 51326.4,
    reward_risk: 2,
    generated_at: "2026-07-09T12:00:00Z",
  },
};

export function latestMockCall(symbol: SymbolCode): MockCallBase {
  return baseCalls[symbol];
}

export function recentMockHistory(symbol: SymbolCode): FreshCallResponse[] {
  const latest = latestMockCall(symbol);

  return [
    {
      ...latest,
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    },
    {
      ...latest,
      call: "stand_aside",
      trade_status: "no_trade",
      decision_summary: "no trade yet; the market still needs a cleaner setup",
      wait_for: "wait for clean structure confirmation",
      generated_at: "2026-07-09T11:45:00Z",
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    },
  ];
}

export const mockSystemStatus = {
  latest_call: "R_100 buy_candidate",
  alert_count: 12,
  suppressed_context_count: 3,
  transport_event_count: 4,
  latest_transport_event: "reconnected",
  latest_transport_reason: "socket recovered after transient disconnect",
  backend_status: "mock_ready",
  journal_status: "fresh",
};

export const mockCurrentPropProfile: PropProfileResponse = {
  profile: "blueberry_2step_funded",
  startingBalance: 100000,
  currentBalance: 100200,
  currentEquity: 100100,
  todaysRealizedLoss: 0,
  todaysFloatingLossExposure: 0,
  highImpactNewsLockout: false,
  telemetry: {
    status: "live_unavailable",
    message: "Live prop check unavailable",
  },
};
