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

/**
 * Strip execution levels from a call that is no longer actionable.
 *
 * When the guardian reports a setup as failing or cancelled, the old
 * entry/stop/target levels are invalid and must never be shown or
 * executed. This helper nulls every price level so no stale number can
 * leak into the lot-size calculator, history panel, or execution flow.
 */
function stripExecutionLevels(call: FreshCallResponse): FreshCallResponse {
  return {
    ...call,
    entry: null,
    stop_loss: null,
    take_profit: null,
    execution_stop: null,
    thesis_invalidation: null,
    primary_target: null,
    extended_target: null,
    entry_area: null,
    stop_area: null,
    target_area: null,
  };
}

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

// The user's symbol choice must survive page reloads.  The engine's focus
// symbol is R_75 (Deriv Volatility 75); persist the selection so a
// refresh never silently snaps back to R_100.
const ACTIVE_SYMBOL_KEY = "synth-active-symbol";

function readPersistedSymbol(): SymbolCode {
  if (typeof localStorage === "undefined") return "R_75";
  const saved = localStorage.getItem(ACTIVE_SYMBOL_KEY);
  return saved === "R_75" || saved === "R_100" ? saved : "R_75";
}

export function useOperatorWorkspace() {
  const [accountMode, setAccountMode] = useState<AccountMode>("own_account");
  const [activeSymbol, setActiveSymbol] = useState<SymbolCode>(readPersistedSymbol);
  const [tradingMode, setTradingMode] = useState<TradingMode>("sniper");
  const [loading, setLoading] = useState(false);
  const [loadingElapsedSeconds, setLoadingElapsedSeconds] = useState(0);
  const [currentCall, setCurrentCall] = useState<FreshCallResponse | null>(null);
  const [guardianStatus, setGuardianStatus] = useState<GuardianStatus | null>(null);
  const [history, setHistory] = useState<FreshCallResponse[]>([]);
  const unavailablePropProfile: PropProfileResponse = {
    profile: "deriv_2step_funded",
    startingBalance: 5000,
    currentBalance: 5000,
    currentEquity: 5000,
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
  const [cachedCallError, setCachedCallError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const successToastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Latest-value refs for the tick-stream freshness effect ────
  // That effect mounts once and must never read stale closures, so it
  // reaches live values through these refs instead of captured state.
  const currentCallRef = useRef<FreshCallResponse | null>(null);
  const activeSymbolRef = useRef<SymbolCode>(activeSymbol);
  const loadingRef = useRef(false);
  const runSymbolRef = useRef<
    ((symbol: SymbolCode, silent?: boolean) => Promise<void>) | null
  >(null);

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
          const fetched = (await response.json()) as GuardianStatus;
          setGuardianStatus(fetched);

          // ── Stale-plan safety ────────────────────────────────
          // When the guardian reports the setup has failed or been
          // cancelled, the old entry/stop/target levels are no longer
          // valid. Strip them from the live call AND the history list
          // so stale numbers never render or get executed anywhere.
          if (
            fetched.guardian_state === "failing" ||
            fetched.guardian_state === "cancelled"
          ) {
            setCurrentCall((previous) => {
              if (!previous) return previous;
              if (
                previous.guardian_state === "failing" ||
                previous.guardian_state === "cancelled"
              ) {
                return previous;
              }
              return {
                ...stripExecutionLevels(previous),
                guardian_state: fetched.guardian_state,
                guardian_reason: fetched.guardian_reason,
              };
            });
            setHistory((previous) =>
              previous.map((entry) =>
                entry.symbol === fetched.symbol &&
                (entry.guardian_state === "confirmed" ||
                  entry.guardian_state === "actionable")
                  ? {
                      ...stripExecutionLevels(entry),
                      guardian_state: fetched.guardian_state,
                      guardian_reason: fetched.guardian_reason,
                    }
                  : entry,
              ),
            );
          }
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

  const autoRefreshRunningRef = useRef(false);

  const runSymbol = async (symbol: SymbolCode, silent = false) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    if (!silent) {
      setLoading(true);
      setLoadingElapsedSeconds(0);
      setActiveSymbol(symbol);
      try {
        localStorage.setItem(ACTIVE_SYMBOL_KEY, symbol);
      } catch {
        // Non-fatal: persistence is best-effort (private mode, storage full).
      }
      setGuardianStatus(null);
      setCurrentCall(null);
      setIntelligence(null);
    }
    setCachedCallError(null);

    // ── Auto-dismiss loading after 90 seconds ──────────────────
    // The Python subprocess has a 60s timeout (LIVE_SNAPSHOT_TIMEOUT_MS)
    // and the bridge retries once (~2 x 25s under load).  Aborting at 45s
    // killed the request mid-retry and surfaced the dreaded "Retry live
    // read" even when the engine was fine — the frontend must outlive the
    // backend's own budget so the real result (success or honest
    // stand-aside) arrives instead of an AbortError fallback.
    const abortTimeout = setTimeout(() => controller.abort(), 90_000);

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

          // ── Auto-record signal for feedback tracking ──────────────
          // When a valid signal is generated, automatically record it
          // so the user can provide feedback (good/bad) and the system
          // can track whether TP or SL was hit.
          if (
            normalizedPayload.trade_status === "valid" &&
            normalizedPayload.entry != null &&
            normalizedPayload.stop_loss != null &&
            normalizedPayload.take_profit != null
          ) {
            void fetch("/api/feedback", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                action: "record_signal",
                symbol: normalizedPayload.symbol,
                direction: normalizedPayload.direction_bias ?? (normalizedPayload.call === "buy_candidate" ? "buy" : "sell"),
                generated_at: normalizedPayload.generated_at,
                entry: normalizedPayload.entry,
                stop_loss: normalizedPayload.stop_loss,
                take_profit: normalizedPayload.take_profit,
                confidence: normalizedPayload.confidence ?? 0.5,
                regime: normalizedPayload.regime ?? "unknown",
                signal_strength: normalizedPayload.signal_strength ?? "weak_buy",
              }),
            }).catch(() => {}); // fire-and-forget
          }

          return;
        }
      }
    } catch {
      // Preserve the last known support data when support routes are unavailable.
    } finally {
      if (!silent) setLoading(false);
    }

    // ── Keep-last-good on background refresh failure ─────────────
    // A silent background refresh (mount auto-refresh, tick-driven
    // refresh, 10-minute timer) must NEVER destroy a working plan: if
    // the fresh Python read fails but we already hold a usable plan,
    // keep it and only surface a note.  Only an explicit manual refresh
    // that fails replaces the plan with the honest "Live read
    // unavailable" fallback — the user explicitly asked for a fresh read
    // there.  Without this, a flaky background read (e.g. a 20-80s
    // subprocess timeout while the market is idle) wiped a perfectly
    // good confirmed plan and the dashboard showed "Live read
    // unavailable" between manual reads.
    if (silent && currentCall && currentCall.guardian_state !== "unavailable") {
      setCachedCallError("Background refresh failed — keeping the last verified plan.");
      return;
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

  // Keep the latest values reachable by the one-shot tick-stream effect.
  currentCallRef.current = currentCall;
  activeSymbolRef.current = activeSymbol;
  loadingRef.current = loading;
  runSymbolRef.current = runSymbol;

  const hasAutoRun = useRef(false);
  useEffect(() => {
    if (hasAutoRun.current) return;
    hasAutoRun.current = true;

    async function loadCachedCallFirst() {
      // Load the last cached call from the journal FIRST — this is instant
      // and prevents signal flip-flopping across page refreshes.
      if (currentCall || loading) return;

      try {
        const response = await fetch(`/api/calls/latest?symbol=${activeSymbol}`);
        if (response.ok) {
          const cached = (await response.json()) as FreshCallResponse;
          if (cached && cached.guardian_state !== "unavailable") {
            // ANY journaled plan is usable for the initial render — including
            // an honest stand_aside.  The market often has no clean setup, and
            // spawning a fresh 5-45s Python read on every mount just to
            // re-confirm "still no setup" is exactly the slow "Pulling
            // data…" experience the operator complained about.  The
            // stale-refresh effect below silently re-reads when the entry
            // ages past 3 minutes, so the plan always self-heals without a
            // blocking spinner on load.
            setCurrentCall(cached);
            setGuardianStatus({
              symbol: cached.symbol,
              guardian_state: cached.guardian_state,
              guardian_reason: cached.guardian_reason,
              current_close: cached.current_close,
              generated_at: cached.generated_at,
            });
            setHistory((previous) =>
              [cached, ...previous.filter((entry) => entry.symbol !== activeSymbol)].slice(0, 6),
            );
            setCachedCallError(null);
            return;
          }
        }
      } catch {
        // Cached call fetch failed — proceed to the fresh-read fallback below.
        setCachedCallError("Cached call unavailable — refreshing live data");
      }

      // No usable cached call (empty journal or unavailable): spawn a fresh
      // read so the trade plan populates automatically on load — the user
      // should never be stranded on a "Retry live read" placeholder.
      // Non-silent so the "Analyzing the market…" state shows while the
      // Python engine runs.
      void runSymbol(activeSymbol);
    }

    void loadCachedCallFirst();
  }, []);

  // ── Auto-refresh stale cached calls on mount ──────────────────
  // When a cached call is loaded on page mount and is older than 3
  // minutes, automatically trigger a silent refresh so the user gets
  // fresh analysis without clicking Refresh.
  const hasAutoRefreshedOnMount = useRef(false);
  useEffect(() => {
    if (hasAutoRefreshedOnMount.current) return;
    if (!currentCall) return;
    if (currentCall.guardian_state === "unavailable") return;
    if (currentCall.call_age_seconds != null && currentCall.call_age_seconds > 180) {
      hasAutoRefreshedOnMount.current = true;
      // Silently refresh — don't show loading state
      autoRefreshRunningRef.current = true;
      void runSymbol(activeSymbol, true).finally(() => {
        autoRefreshRunningRef.current = false;
      });
    } else {
      hasAutoRefreshedOnMount.current = true;
    }
  }, [currentCall, activeSymbol]);

  // ── Auto-refresh stale cached calls (10-minute background refresh) ──
  // When a cached call is older than 10 minutes, silently refresh in the background
  // so the user eventually gets fresh data without manual intervention.
  useEffect(() => {
    if (!currentCall || currentCall.guardian_state === "unavailable" || currentCall.call_age_seconds == null) return;

    const STALE_THRESHOLD = 600; // 10 minutes in seconds
    const CHECK_INTERVAL = 60_000; // Check every 60 seconds

    const intervalId = setInterval(() => {
      if (
        currentCall.call_age_seconds != null &&
        currentCall.call_age_seconds > STALE_THRESHOLD &&
        !loading &&
        !autoRefreshRunningRef.current
      ) {
        // Silently refresh — don't show loading state, just update in background
        autoRefreshRunningRef.current = true;
        // eslint-disable-next-line @typescript-eslint/no-floating-promises
        runSymbol(activeSymbol, true).finally(() => {
          autoRefreshRunningRef.current = false;
        });
      }
    }, CHECK_INTERVAL);

    return () => clearInterval(intervalId);
  }, [currentCall?.call_age_seconds, loading, activeSymbol]);

  // ── Tick-stream plan freshness ────────────────────────────────
  // R_75 and R_100 ticks already stream through the shared /api/ticks
  // EventSource feed that powers the price chart.  Use that SAME feed to
  // keep the trade plan fresh between manual reads:
  //   • the plan's displayed price (current_close) follows live ticks,
  //   • while ticks are actually flowing and the plan is older than 4
  //     minutes, a silent background refresh re-reads the engine
  //     (throttled to once per 4 minutes), so the plan never sits stale
  //     waiting for a manual Refresh.
  // Plan age is computed live from generated_at — the stored
  // call_age_seconds field is frozen at journal-write time, so the older
  // 10-minute timer never fires for journaled plans.
  // When EventSource is unavailable (tests, old browsers) or the server
  // rejects the stream, fall back to a lightweight 15s /api/ticks poll.
  useEffect(() => {
    if (typeof EventSource === "undefined" || typeof fetch !== "function") {
      return;
    }

    let es: EventSource | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let disposed = false;

    const lastTickAt: Record<string, number> = { R_75: 0, R_100: 0 };
    let lastTickDrivenRefreshAt = 0;

    const TICK_REFRESH_AGE_MS = 4 * 60_000; // plan older than 4 min
    const TICK_FLOW_WINDOW_MS = 90_000; // ticks seen within the last 90s
    const TICK_REFRESH_MIN_INTERVAL_MS = 4 * 60_000;

    function refreshIfDue() {
      const call = currentCallRef.current;
      if (!call || call.guardian_state === "unavailable") return;
      const planMs = Date.parse(call.generated_at);
      if (!Number.isFinite(planMs)) return;
      if (Date.now() - planMs < TICK_REFRESH_AGE_MS) return;
      const symbol = activeSymbolRef.current;
      const lastTick = lastTickAt[symbol];
      if (!lastTick || Date.now() - lastTick > TICK_FLOW_WINDOW_MS) return;
      const now = Date.now();
      if (now - lastTickDrivenRefreshAt < TICK_REFRESH_MIN_INTERVAL_MS) return;
      if (loadingRef.current || autoRefreshRunningRef.current) return;
      lastTickDrivenRefreshAt = now;
      autoRefreshRunningRef.current = true;
      void runSymbolRef.current?.(symbol, true).finally(() => {
        autoRefreshRunningRef.current = false;
      });
    }

    function handleTick(symbol: string, epoch: number, price: number) {
      if (symbol !== "R_75" && symbol !== "R_100") return;
      lastTickAt[symbol] = Date.now();
      if (symbol !== activeSymbolRef.current) return;

      // Live-update the plan's displayed price — no Python read needed.
      setCurrentCall((previous) => {
        if (!previous) return previous;
        const planMs = Date.parse(previous.generated_at);
        if (!Number.isFinite(planMs) || epoch * 1000 < planMs) return previous;
        if (previous.current_close === price) return previous;
        return { ...previous, current_close: price };
      });
      setGuardianStatus((previous) =>
        previous && previous.current_close !== price
          ? { ...previous, current_close: price }
          : previous,
      );

      refreshIfDue();
    }

    function startPolling() {
      if (pollTimer) return;
      const pollOnce = async () => {
        try {
          const res = await fetch("/api/ticks?limit=10");
          if (!res.ok) return;
          const json = (await res.json()) as {
            ticks?: Record<string, Array<{ epoch: number; price: number }>>;
          };
          const symbol = activeSymbolRef.current;
          const ticks = json.ticks?.[symbol];
          const last =
            ticks && ticks.length > 0 ? ticks[ticks.length - 1] : null;
          if (last) handleTick(symbol, last.epoch, last.price);
        } catch {
          // A failed poll never destroys state — keep the last known price.
        }
      };
      void pollOnce();
      pollTimer = setInterval(() => void pollOnce(), 15_000);
    }

    function openStream() {
      if (disposed) return;
      try {
        es = new EventSource("/api/ticks?stream=true&limit=10");
      } catch {
        startPolling();
        return;
      }
      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as {
            type?: string;
            symbol?: string;
            ticks?: Array<{ epoch: number; price: number }>;
            tick?: { epoch: number; price: number };
          };
          if (
            data.type === "initial" &&
            data.symbol &&
            Array.isArray(data.ticks)
          ) {
            const last = data.ticks[data.ticks.length - 1];
            if (last) handleTick(data.symbol, last.epoch, last.price);
          } else if (data.type === "tick" && data.symbol && data.tick) {
            handleTick(data.symbol, data.tick.epoch, data.tick.price);
          } else if (data.type === "error") {
            es?.close();
            es = null;
            startPolling();
          }
        } catch {
          // Ignore malformed events.
        }
      };
      es.onerror = () => {
        es?.close();
        es = null;
        startPolling();
      };
    }

    openStream();

    return () => {
      disposed = true;
      es?.close();
      if (pollTimer) clearInterval(pollTimer);
    };
  }, []);

  // ── Periodic trade outcome resolution ───────────────────────
  // Every 5 minutes, trigger bulk_resolve to check whether executed
  // trades have hit TP or SL after the hold horizon.  This closes
  // the learning loop: Execute → wait 6 hours → outcome resolved →
  // fed into calibration so probabilities improve.
  useEffect(() => {
    const RESOLVE_INTERVAL = 5 * 60_000; // 5 minutes

    const intervalId = setInterval(() => {
      void fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "bulk_resolve" }),
      }).catch(() => {}); // fire-and-forget
    }, RESOLVE_INTERVAL);

    // Also run once on mount so any signals that expired while the page was closed get resolved
    void fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "bulk_resolve" }),
    }).catch(() => {});

    return () => clearInterval(intervalId);
  }, []);

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

    // Stage-3 empirical sizing: risk scales with empirical confidence.  The
    // collapsed gate answers one question (full / half / paper): a call with
    // no empirical verdict yet (or evidence below the floor) sizes 0.0 — it
    // may be paper-traded (that generates the outcomes the gate needs) but
    // must never place a real MT5 order.  There is no annotate escape hatch
    // and no proven-only belt anymore.  Fail closed: a payload with no
    // stage3 authorization (missing block, the gate marked it not
    // executable, or an internally inconsistent stale payload) can never
    // place a live order even if it claims a positive size.
    const sizeMultiplier = currentCall.size_multiplier ?? 1;
    const stage3Block = currentCall.stage3;
    const explicitAllowed = stage3Block?.execution_allowed;
    const allowed =
      explicitAllowed !== undefined
        ? explicitAllowed
        : stage3Block != null &&
          (stage3Block.state === "gated" || stage3Block.state === "annotated");
    if (executionMode === "live_mt5" && (sizeMultiplier <= 0 || !allowed)) {
      setExecutionError(
        "This call type is paper-only (no empirical verdict yet, or below the verified floor) — no live MT5 order was placed. Run it on paper to build the scored outcomes the gate needs; only market-verified call types size up to live size.",
      );
      return;
    }

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
          // Scale the base lot by the Stage-3 empirical multiplier (floored at
          // the broker's 0.01 minimum); paper_only calls were already blocked
          // above, so the multiplier here is always > 0.
          mt5_volume:
            executionMode === "live_mt5"
              ? Math.max(0.01, 0.01 * Math.min(sizeMultiplier, 1))
              : undefined,
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

          // ── Record execution in feedback tracker ───────────────
          // Mark the signal as "executed" (NOT resolved) so the
          // bulk_resolve checker can later determine the real outcome
          // (TP hit, SL hit, etc.) and feed it into calibration.
          const execSignalId = `${currentCall.symbol}_${currentCall.generated_at.replace(/:/g, "-").replace(/\./g, "-")}`;
          void fetch("/api/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: "record_execution",
              signal_id: execSignalId,
            }),
          }).catch(() => {}); // fire-and-forget

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
          // ── Record close outcome in feedback tracker ────────
          // Determine whether TP or SL was hit based on close price
          // vs entry/SL/TP, then record the outcome immediately
          // so it feeds into calibration without waiting for bulk_resolve.
          const closeSignalId = `${trackedPosition.symbol}_${currentCall?.generated_at?.replace(/:/g, "-").replace(/\./g, "-") ?? ""}`;
          const closePrice = trackedPosition.current_price ?? trackedPosition.entry_price;
          const entry = trackedPosition.entry_price;
          const sl = trackedPosition.stop_loss;
          const tp = trackedPosition.take_profit;
          const dir = trackedPosition.direction;

          let outcome = "manual_close";
          let pnlPips = 0;
          let rMultiple = 0;
          const stopDist = Math.abs(entry - sl);

          if (dir === "buy") {
            if (closePrice >= tp) { outcome = "tp_hit"; }
            else if (closePrice <= sl) { outcome = "sl_hit"; }
            pnlPips = closePrice - entry;
          } else {
            if (closePrice <= tp) { outcome = "tp_hit"; }
            else if (closePrice >= sl) { outcome = "sl_hit"; }
            pnlPips = entry - closePrice;
          }
          rMultiple = stopDist > 0 ? pnlPips / stopDist : 0;

          void fetch("/api/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: "record_outcome",
              signal_id: closeSignalId,
              outcome,
              outcome_price: closePrice,
              pnl_pips: pnlPips,
              r_multiple: rMultiple,
            }),
          }).catch(() => {}); // fire-and-forget

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
  cachedCallError,
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
