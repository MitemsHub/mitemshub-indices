"use client";

import { useEffect, useRef, useState } from "react";
import type {
  AccountMode,
  FreshCallResponse,
  GuardianStatus,
  IntelligencePayload,
  PropConnectionInput,
  PropProfileResponse,
  TradingMode,
} from "../lib/contracts";
import {
  evaluatePropCompliance,
  type PropAccountState,
} from "../lib/prop-policy";
import type { ExecutionMode, SubmitOrderResponse, TrackedPosition } from "../lib/contracts";
import { useNotifications } from "./use-notifications";

type SymbolCode = FreshCallResponse["symbol"];
type SystemStatus = {
  latest_call: string;
  alert_count: number;
  suppressed_context_count: number;
  transport_event_count: number;
  latest_transport_event: string;
  latest_transport_reason: string;
  backend_status: string;
};

function buildUnavailableCall(
  symbol: SymbolCode,
  accountMode: AccountMode,
  propAccountState: PropAccountState | null,
  detail: string,
): FreshCallResponse {
  const base = {
    symbol,
    call: "stand_aside" as const,
    alert_type: "context_update",
    trade_status: "not_valid",
    confidence: null,
    regime: null,
    direction_bias: null,
    why: `Live market read unavailable. ${detail}`,
    wait_for: "wait for the live bridge to reconnect, then refresh the call",
    decision_summary: "Live market read unavailable. Refresh after the live bridge reconnects.",
    entry_area: null,
    stop_area: null,
    target_area: null,
    entry: null,
    stop_loss: null,
    take_profit: null,
    execution_stop: null,
    thesis_invalidation: null,
    primary_target: null,
    extended_target: null,
    hold_horizon_minutes: null,
    reward_risk: null,
    signal_strength: null,
    position_sizing: null,
    current_close: null,
    guardian_state: "unavailable" as const,
    guardian_reason: `Live market read unavailable. ${detail}`,
    invalidates_if: null,
    call_age_seconds: null,
    generated_at: new Date().toISOString(),
  };

  if (accountMode === "own_account") {
    return {
      ...base,
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    };
  }

  const compliance = evaluatePropCompliance({
    call: base,
    accountState: propAccountState,
    proposedRiskPercent: 1,
  });

  return {
    ...base,
    account_mode: "prop_firm",
    prop_compliance: compliance.status,
    prop_adjusted_risk: compliance.adjustedRiskPercent,
    prop_block_reason: compliance.blockReason,
    prop_remaining_daily_buffer: compliance.remainingDailyBuffer,
    prop_remaining_overall_buffer: compliance.remainingOverallBuffer,
  };
}

export function useOperatorWorkspace() {
  const [accountMode, setAccountMode] = useState<AccountMode>("own_account");
  const [activeSymbol, setActiveSymbol] = useState<SymbolCode>("R_100");
  const [tradingMode, setTradingMode] = useState<TradingMode>("sniper");
  const [loading, setLoading] = useState(false);
  const [loadingElapsedSeconds, setLoadingElapsedSeconds] = useState(0);
  const [currentCall, setCurrentCall] = useState<FreshCallResponse | null>(null);
  const [guardianStatus, setGuardianStatus] = useState<GuardianStatus | null>(null);
  const [history, setHistory] = useState<FreshCallResponse[]>([]);
  const unavailablePropProfile: PropProfileResponse = {
    profile: "blueberry_2step_funded",
    startingBalance: 100000,
    currentBalance: 0,
    currentEquity: 0,
    todaysRealizedLoss: 0,
    todaysFloatingLossExposure: 0,
    highImpactNewsLockout: false,
    telemetry: {
      status: "live_unavailable" as const,
      message: "MT5 not configured or unreachable — no prop profile available",
    },
  };
  const defaultSystemStatus: SystemStatus = {
    latest_call: "Bridge running",
    alert_count: 0,
    suppressed_context_count: 0,
    transport_event_count: 0,
    latest_transport_event: "live_bridge_ready",
    latest_transport_reason: "Engine bridge initialised",
    backend_status: "live_bridge_ready",
  };
  const [systemStatus, setSystemStatus] = useState<SystemStatus>(defaultSystemStatus);
  const [propProfile, setPropProfile] = useState<PropProfileResponse>(
    unavailablePropProfile,
  );
  const [propConnectionDraftOpen, setPropConnectionDraftOpen] = useState(false);
  const [propConnection, setPropConnection] = useState<PropConnectionInput | null>(null);
  const [propConnectionStatus, setPropConnectionStatus] = useState<
    "idle" | "using_own_account_fallback" | "using_dedicated_prop_account"
  >("idle");
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("paper");
  const [trackedPosition, setTrackedPosition] = useState<TrackedPosition | null>(null);
  const [executing, setExecuting] = useState(false);
  const [executionError, setExecutionError] = useState<string | null>(null);
  const [executionSuccess, setExecutionSuccess] = useState<string | null>(null);
  const [confirmModalOpen, setConfirmModalOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const successToastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clean up success toast timer on unmount
  useEffect(() => {
    return () => {
      if (successToastTimerRef.current) clearTimeout(successToastTimerRef.current);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadSupportData() {
      if (typeof fetch !== "function") {
        return;
      }

      try {
        const [historyResponse, statusResponse, propResponse] = await Promise.all([
          fetch(`/api/history?symbol=${activeSymbol}`),
          fetch("/api/system/status"),
          fetch("/api/prop-profiles/current"),
        ]);

        if (!cancelled && historyResponse.ok) {
          const payload = (await historyResponse.json()) as {
            history?: FreshCallResponse[];
          };
          if (Array.isArray(payload.history) && payload.history.length > 0) {
            setHistory(payload.history);
          }
        }

        if (!cancelled && statusResponse.ok) {
          const payload = (await statusResponse.json()) as SystemStatus;
          setSystemStatus(payload);
        }

        if (!cancelled && propResponse.ok) {
          const payload = (await propResponse.json()) as PropProfileResponse;
          setPropProfile(payload);
        }
      } catch {
        // Keep deterministic fallback data when support routes are unavailable.
      }
    }

    void loadSupportData();

    return () => {
      cancelled = true;
    };
  }, [activeSymbol]);

  useEffect(() => {
    if (!loading) {
      setLoadingElapsedSeconds(0);
      return;
    }

    const intervalId = window.setInterval(() => {
      setLoadingElapsedSeconds((previous) => previous + 1);
    }, 1000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [loading]);

  useEffect(() => {
    if (!currentCall) {
      setGuardianStatus(null);
      return;
    }

    setGuardianStatus({
      symbol: currentCall.symbol,
      guardian_state: currentCall.guardian_state,
      guardian_reason: currentCall.guardian_reason,
      current_close: currentCall.current_close,
      generated_at: currentCall.generated_at,
    });

    if (typeof fetch !== "function") {
      return;
    }

    let cancelled = false;

    const pollGuardian = async () => {
      try {
        const response = await fetch(
          `/api/calls/guardian?symbol=${currentCall.symbol}&trading_mode=${tradingMode}`,
        );
        if (!cancelled && response.ok) {
          setGuardianStatus((await response.json()) as GuardianStatus);
        }
      } catch {
        // Keep the last known guardian truth when polling fails.
      }
    };

    void pollGuardian();
    const intervalId = window.setInterval(() => {
      void pollGuardian();
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [currentCall, tradingMode]);

  const requestPropMode = () => {
    setPropConnectionDraftOpen(true);
  };

  const cancelPropModeRequest = () => {
    setPropConnectionDraftOpen(false);
  };

  const confirmPropMode = async (value: PropConnectionInput) => {
    const usingDedicatedConnection = Boolean(
      value.server && value.login && value.password,
    );
    const nextConnection = usingDedicatedConnection
      ? value
      : {
          server: null,
          login: null,
          password: null,
          terminalPath: null,
          startingBalance: value.startingBalance,
        };

    setPropConnection(nextConnection);
    setPropConnectionStatus(
      usingDedicatedConnection
        ? "using_dedicated_prop_account"
        : "using_own_account_fallback",
    );
    setAccountMode("prop_firm");
    setPropConnectionDraftOpen(false);

    try {
      if (typeof fetch !== "function") {
        return;
      }

      const response = await fetch("/api/prop-profiles/current", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          connection: usingDedicatedConnection
            ? {
                server: nextConnection.server,
                login: nextConnection.login,
                password: nextConnection.password,
                terminalPath: nextConnection.terminalPath,
              }
            : null,
          startingBalance: nextConnection.startingBalance,
        }),
      });

      if (response.ok) {
        setPropProfile((await response.json()) as PropProfileResponse);
      }
    } catch {
      // Keep the current session state even when live prop telemetry is unavailable.
    }
  };

  const stopRefresh = async () => {
    if (loading) {
      // Cancel the Python subprocess on the server first (fire-and-forget)
      if (typeof fetch === "function") {
        void fetch("/api/calls/cancel", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            symbol: activeSymbol,
            trading_mode: tradingMode,
          }),
        }).catch(() => {});
      }

      abortRef.current?.abort();
      abortRef.current = null;
      setLoading(false);
      setLoadingElapsedSeconds(0);
    } else if (activeSymbol) {
      void runSymbol(activeSymbol);
    }
  };

  const runSymbol = async (symbol: SymbolCode) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setLoadingElapsedSeconds(0);
    setActiveSymbol(symbol);
    setGuardianStatus(null);
    setCurrentCall(null);
    setIntelligence(null);

    // ── Auto-dismiss loading after 30 seconds ──────────────────
    // Prevents the "Still loading…" state from persisting forever
    // when the Python subprocess hangs or the server is unreachable.
    // The AbortController already supports manual cancellation via
    // the Stop button; this adds an automatic safety net.
    const abortTimeout = setTimeout(() => controller.abort(), 30_000);

    try {
      if (typeof fetch === "function") {
        const response = await fetch("/api/calls/run", {
          signal: controller.signal,
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            symbol,
            account_mode: accountMode,
            trading_mode: tradingMode,
            prop_account_state:
              accountMode === "prop_firm" ? propProfile : null,
            prop_connection:
              accountMode === "prop_firm" ? propConnection : null,
          }),
        });

        clearTimeout(abortTimeout);
        if (response.ok) {
          const payload = (await response.json()) as FreshCallResponse;

          const normalizedPayload: FreshCallResponse = {
            ...payload,
            invalidates_if: payload.invalidates_if ?? null,
            call_age_seconds: payload.call_age_seconds ?? null,
            execution_stop: payload.execution_stop ?? null,
            thesis_invalidation: payload.thesis_invalidation ?? null,
            primary_target: payload.primary_target ?? null,
            extended_target: payload.extended_target ?? null,
            hold_horizon_minutes: payload.hold_horizon_minutes ?? null,
          };

          setCurrentCall(normalizedPayload);
          setGuardianStatus({
            symbol: normalizedPayload.symbol,
            guardian_state: normalizedPayload.guardian_state,
            guardian_reason: normalizedPayload.guardian_reason,
            current_close: normalizedPayload.current_close,
            generated_at: normalizedPayload.generated_at,
          });
          setHistory((previous) =>
            [
              normalizedPayload,
              ...previous.filter((entry) => entry.symbol !== symbol),
            ].slice(
              0,
              6,
            ),
          );

          return;
        }
      }
    } catch {
      // Preserve the last known support data when support routes are unavailable.
    } finally {
      setLoading(false);
    }

    const fallback = buildUnavailableCall(
      symbol,
      accountMode,
      accountMode === "prop_firm" ? propProfile : null,
      "The app could not confirm a fresh price from the bridge.",
    );

    setCurrentCall(fallback);
    setGuardianStatus({
      symbol: fallback.symbol,
      guardian_state: fallback.guardian_state,
      guardian_reason: fallback.guardian_reason,
      current_close: fallback.current_close,
      generated_at: fallback.generated_at,
    });
    setHistory((previous) =>
      [fallback, ...previous.filter((entry) => entry.symbol !== symbol)].slice(
        0,
        6,
      ),
    );
  };
  const hasAutoRun = useRef(false);
  useEffect(() => {
    if (hasAutoRun.current) return;
    hasAutoRun.current = true;

    async function autoRunLiveCall() {
      // Only run once on initial mount
      if (!currentCall && !loading) {
        try {
          await runSymbol(activeSymbol);
        } catch {
          // Ignore errors, fallback will be shown
        }
      }
    }

    void autoRunLiveCall();
  }, [currentCall, loading, activeSymbol, runSymbol]);

  // Re-run when trading mode changes to get a fresh call with new parameters
  const prevTradingMode = useRef(tradingMode);
  const switchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (prevTradingMode.current !== tradingMode && currentCall) {
      prevTradingMode.current = tradingMode;
      if (switchDebounceRef.current) {
        clearTimeout(switchDebounceRef.current);
      }
      switchDebounceRef.current = setTimeout(() => {
        void runSymbol(activeSymbol);
      }, 300);
    } else {
      prevTradingMode.current = tradingMode;
    }
    return () => {
      if (switchDebounceRef.current) {
        clearTimeout(switchDebounceRef.current);
      }
    };
  }, [tradingMode, currentCall, activeSymbol]);

  /** Phase 1: open the confirmation modal (or skip for paper mode). */
  const requestTradeConfirm = () => {
    if (!currentCall || currentCall.trade_status !== "valid" || !currentCall.entry) return;
    if (!currentCall.stop_loss || !currentCall.take_profit) return;

    // Clear any previous execution error
    setExecutionError(null);

    if (executionMode === "live_mt5") {
      // Show the professional confirmation modal for live trades
      setConfirmModalOpen(true);
    } else {
      // Paper trades execute immediately — no modal needed
      void executeTradeOrder();
    }
  };

  /** Phase 2: called by the modal's Confirm button or directly for paper mode. */
  const executeTradeOrder = async (overrides?: { entry?: number; stopLoss?: number; takeProfit?: number }) => {
    if (!currentCall || currentCall.trade_status !== "valid" || !currentCall.entry) return;
    if (!currentCall.stop_loss || !currentCall.take_profit) return;

    const entry = overrides?.entry ?? currentCall.entry;
    const stopLoss = overrides?.stopLoss ?? currentCall.stop_loss ?? currentCall.entry;
    const takeProfit = overrides?.takeProfit ?? currentCall.take_profit ?? currentCall.entry;

    setExecuting(true);
    setExecutionError(null);
    try {
      const response = await fetch("/api/execution/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: currentCall.symbol,
          direction_bias: currentCall.direction_bias,
          entry,
          stop_loss: stopLoss,
          take_profit: takeProfit,
          execution_stop: currentCall.execution_stop,
          thesis_invalidation: currentCall.thesis_invalidation,
          primary_target: currentCall.primary_target,
          extended_target: currentCall.extended_target,
          execution_mode: executionMode,
          mt5_volume: executionMode === "live_mt5" ? 0.01 : undefined,
        }),
      });

      if (response.ok) {
        const result = (await response.json()) as SubmitOrderResponse;
        if (result.accepted && result.position_id) {
          setTrackedPosition({
            position_id: result.position_id,
            symbol: currentCall.symbol,
            direction: currentCall.direction_bias === "sell" ? "sell" : "buy",
            entry_price: result.entry_price ?? entry,
            stop_loss: result.stop_loss ?? stopLoss,
            take_profit: result.take_profit ?? takeProfit,
            current_price: currentCall.current_close,
            opened_at: new Date().toISOString(),
            execution_mode: executionMode,
            mt5_ticket: executionMode === "live_mt5" ? Number(result.position_id) : null,
          });
          // Show success toast
          const successMsg = executionMode === "live_mt5"
            ? `Trade executed on MT5 — Position #${result.position_id}`
            : `Paper trade recorded — Position #${result.position_id}`;
          setExecutionError(null);
          setExecutionSuccess(successMsg);
          // Auto-dismiss success toast after 5 seconds (stored ref for cleanup)
          successToastTimerRef.current = setTimeout(() => setExecutionSuccess(null), 5000);
          // Close modal on success (live mode only — paper skips modal)
          if (executionMode === "live_mt5") {
            setConfirmModalOpen(false);
          }
        } else {
          // Order rejected — surface the error message from the backend
          const errorMsg = result.message || "Order was rejected by the broker.";
          setExecutionError(errorMsg);
          console.error("[execution] Order rejected:", errorMsg);
        }
        return result;
      } else {
        // HTTP error
        const errorBody = await response.json().catch(() => null);
        const errorMsg = errorBody?.error || `Server error (${response.status})`;
        setExecutionError(errorMsg);
        console.error("[execution] HTTP error:", response.status, errorMsg);
      }
    } catch (err) {
      // Network error or unexpected failure
      const errorMsg = err instanceof Error ? err.message : "Network error — could not reach the server.";
      setExecutionError(errorMsg);
      console.error("[execution] Network error:", err);
    } finally {
      setExecuting(false);
    }
    return null;
  };

  const confirmModalConfirm = (params?: { entry: number; stopLoss: number; takeProfit: number }) => {
    void executeTradeOrder(params);
  };

  const confirmModalCancel = () => {
    setConfirmModalOpen(false);
    setExecutionError(null);
    setExecutionSuccess(null);
    if (successToastTimerRef.current) {
      clearTimeout(successToastTimerRef.current);
      successToastTimerRef.current = null;
    }
  };

  const closeTrackedPosition = async () => {
    if (!trackedPosition) return;

    setExecuting(true);
    try {
      const response = await fetch("/api/execution/close", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          position_id: trackedPosition.position_id,
          execution_mode: trackedPosition.execution_mode,
          mt5_ticket: trackedPosition.mt5_ticket,
        }),
      });

      if (response.ok) {
        const result = await response.json();
        if (result.closed) {
          setTrackedPosition(null);
        }
        return result;
      }
    } catch {
      // Keep current state on failure
    } finally {
      setExecuting(false);
    }
    return null;
  };

const propCallPreview =
  accountMode !== "prop_firm" || currentCall ? currentCall : null;

// Fetch intelligence data when call is available
const [intelligence, setIntelligence] = useState<IntelligencePayload | null>(null);
const [intelligenceLoading, setIntelligenceLoading] = useState(false);

useEffect(() => {
    if (!currentCall) {
      setIntelligence(null);
      return;
    }

    const symbol = currentCall.symbol;
    let cancelled = false;

    async function loadIntelligence() {
      setIntelligenceLoading(true);
      try {
        const symbolHistory = history.filter((entry) => entry.symbol === symbol);
        const response = await fetch("/api/intelligence", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            call: currentCall,
            symbol,
            history: symbolHistory,
          }),
        });
        if (!cancelled && response.ok) {
          const data = await response.json();
          // Treat all-null response (from an unavailable call) as null intelligence
          // Check the nullable data fields — boolean flags like using_prepared_call should NOT count as data
          const dataFields = [
            data?.market_intelligence,
            data?.evidence_summary,
            data?.market_thesis,
            data?.confidence_breakdown,
            data?.trade_plan,
            data?.risk_assessment,
          ];
          const hasAnyData = dataFields.some((v) => v != null);
          if (!hasAnyData && !cancelled) {
            console.warn('[intelligence] API returned all-null data for call state', currentCall?.guardian_state, currentCall?.call, 'raw_features present:', !!currentCall?.raw_features, 'symbol:', symbol);
          }
          setIntelligence(hasAnyData ? data : null);
        } else if (!cancelled) {
          console.warn('[intelligence] API returned non-OK status:', response.status, 'for call state', currentCall?.guardian_state);
          setIntelligence(null);
        }
      } catch {
        if (!cancelled) setIntelligence(null);
      } finally {
        if (!cancelled) setIntelligenceLoading(false);
      }
    }

    loadIntelligence();

    return () => {
      cancelled = true;
    };
  }, [currentCall, tradingMode]);

// ── Browser push notifications ──────────────────────────────
const notifications = useNotifications(currentCall);

return {
  accountMode,
  activeSymbol,
  cancelPropModeRequest,
  closeTrackedPosition,
  confirmPropMode,
  currentCall,
  executing,
  executionMode,
  guardianStatus,
  history,
  loading,
  loadingElapsedSeconds,
  notifications,
  propCallPreview,
  propConnection,
  propConnectionDraftOpen,
  propConnectionStatus,
  propProfile,
  requestPropMode,
  setAccountMode,
  setExecutionMode,
  setTradingMode,
  stopRefresh,
  submitTradeOrder: requestTradeConfirm,
  executeTradeOrder,
  executionError,
  executionSuccess,
  confirmModalOpen,
  confirmModalConfirm,
  confirmModalCancel,
  trackedPosition,
  tradingMode,
  runSymbol,
  systemStatus,
  intelligence,
  intelligenceLoading,
};
}
