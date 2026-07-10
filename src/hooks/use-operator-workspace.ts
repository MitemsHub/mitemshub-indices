"use client";

import { useEffect, useMemo, useState } from "react";
import type {
  AccountMode,
  FreshCallResponse,
  PropConnectionInput,
  PropProfileResponse,
} from "../lib/contracts";
import {
  latestMockCall,
  mockCurrentPropProfile,
  mockSystemStatus,
  recentMockHistory,
} from "../lib/mock-data";
import {
  evaluatePropCompliance,
  type PropAccountState,
} from "../lib/prop-policy";

type SymbolCode = FreshCallResponse["symbol"];
type SystemStatus = typeof mockSystemStatus;

function buildFallbackCall(
  symbol: SymbolCode,
  accountMode: AccountMode,
  propAccountState: PropAccountState | null,
): FreshCallResponse {
  const base = latestMockCall(symbol);

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
  const [loading, setLoading] = useState(false);
  const [currentCall, setCurrentCall] = useState<FreshCallResponse | null>(null);
  const [history, setHistory] = useState<FreshCallResponse[]>(recentMockHistory("R_100"));
  const [systemStatus, setSystemStatus] = useState<SystemStatus>(mockSystemStatus);
  const [propProfile, setPropProfile] = useState<PropProfileResponse>(
    mockCurrentPropProfile,
  );
  const [propConnectionDraftOpen, setPropConnectionDraftOpen] = useState(false);
  const [propConnection, setPropConnection] = useState<PropConnectionInput | null>(null);
  const [propConnectionStatus, setPropConnectionStatus] = useState<
    "idle" | "using_own_account_fallback" | "using_dedicated_prop_account"
  >("idle");

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

  const runSymbol = async (symbol: SymbolCode) => {
    setLoading(true);
    setActiveSymbol(symbol);

    try {
      if (typeof fetch === "function") {
        const response = await fetch("/api/calls/run", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            symbol,
            account_mode: accountMode,
            prop_account_state:
              accountMode === "prop_firm" ? propProfile : null,
            prop_connection:
              accountMode === "prop_firm" ? propConnection : null,
          }),
        });

        if (response.ok) {
          const payload = (await response.json()) as FreshCallResponse;

          setCurrentCall(payload);
          setHistory((previous) =>
            [payload, ...previous.filter((entry) => entry.symbol !== symbol)].slice(
              0,
              6,
            ),
          );

          return;
        }
      }
    } catch {
      // Use deterministic local data in tests and when the local bridge is unavailable.
    } finally {
      setLoading(false);
    }

    const fallback = buildFallbackCall(
      symbol,
      accountMode,
      accountMode === "prop_firm" ? propProfile : null,
    );

    setCurrentCall(fallback);
    setHistory((previous) =>
      [fallback, ...previous.filter((entry) => entry.symbol !== symbol)].slice(
        0,
        6,
      ),
    );
  };

  const propCallPreview = useMemo(() => {
    if (accountMode !== "prop_firm") {
      return currentCall;
    }

    if (currentCall) {
      return currentCall;
    }

    return buildFallbackCall("R_100", "prop_firm", propProfile);
  }, [accountMode, currentCall, propProfile]);

  return {
    accountMode,
    cancelPropModeRequest,
    confirmPropMode,
    currentCall,
    history,
    loading,
    propCallPreview,
    propConnection,
    propConnectionDraftOpen,
    propConnectionStatus,
    propProfile,
    requestPropMode,
    setAccountMode,
    runSymbol,
    systemStatus,
  };
}
