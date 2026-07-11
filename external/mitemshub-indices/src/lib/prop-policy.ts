import type { FreshCallResponse, PropCompliance } from "./contracts";

export type PropAccountState = {
  profile: "blueberry_2step_funded";
  startingBalance: number;
  currentBalance: number;
  currentEquity: number;
  todaysRealizedLoss: number;
  todaysFloatingLossExposure: number;
  highImpactNewsLockout: boolean;
};

export type PropPolicyResult = {
  status: PropCompliance;
  adjustedRiskPercent: number | null;
  remainingDailyBuffer: number | null;
  remainingOverallBuffer: number | null;
  blockReason: string | null;
};

type PolicyCall = Pick<
  FreshCallResponse,
  "symbol" | "call" | "entry" | "stop_loss" | "reward_risk"
>;

export function evaluatePropCompliance({
  call,
  accountState,
  proposedRiskPercent,
}: {
  call: PolicyCall;
  accountState: PropAccountState | null;
  proposedRiskPercent: number;
}): PropPolicyResult {
  if (!accountState) {
    return {
      status: "insufficient_account_state",
      adjustedRiskPercent: null,
      remainingDailyBuffer: null,
      remainingOverallBuffer: null,
      blockReason: "prop account state is missing",
    };
  }

  const dailyLimit = accountState.startingBalance * 0.05;
  const overallFloor = accountState.startingBalance * 0.9;
  const remainingDailyBuffer =
    dailyLimit -
    accountState.todaysRealizedLoss -
    accountState.todaysFloatingLossExposure;
  const remainingOverallBuffer = accountState.currentEquity - overallFloor;

  if (accountState.highImpactNewsLockout) {
    return {
      status: "blocked",
      adjustedRiskPercent: null,
      remainingDailyBuffer,
      remainingOverallBuffer,
      blockReason: "high-impact news lockout is active",
    };
  }

  if (remainingDailyBuffer <= 0) {
    return {
      status: "blocked",
      adjustedRiskPercent: null,
      remainingDailyBuffer,
      remainingOverallBuffer,
      blockReason: "daily loss buffer exhausted",
    };
  }

  if (remainingOverallBuffer <= 0) {
    return {
      status: "blocked",
      adjustedRiskPercent: null,
      remainingDailyBuffer,
      remainingOverallBuffer,
      blockReason: "overall drawdown buffer exhausted",
    };
  }

  if (call.call === "stand_aside") {
    return {
      status: "allowed",
      adjustedRiskPercent: 0,
      remainingDailyBuffer,
      remainingOverallBuffer,
      blockReason: null,
    };
  }

  if (proposedRiskPercent > 1.5) {
    return {
      status: "allowed_with_adjustment",
      adjustedRiskPercent: 1.5,
      remainingDailyBuffer,
      remainingOverallBuffer,
      blockReason: null,
    };
  }

  return {
    status: "allowed",
    adjustedRiskPercent: proposedRiskPercent,
    remainingDailyBuffer,
    remainingOverallBuffer,
    blockReason: null,
  };
}
