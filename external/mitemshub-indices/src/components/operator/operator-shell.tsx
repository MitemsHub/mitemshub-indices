"use client";

import React, { useState, useEffect } from "react";
import { useOperatorWorkspace } from "../../hooks/use-operator-workspace";
import { useMediaQuery } from "../../hooks/use-media-query";
import { CommandBar } from "./command-bar";
import { HistoryPanel } from "./history-panel";
import { PrimaryCallPanel } from "./primary-call-panel";
import { PropConnectionModal } from "./prop-connection-modal";
import { PropCompliancePanel } from "./prop-compliance-panel";
import { TradeInstructionPanel } from "./trade-instruction-panel";
import { SkeletonLoader, CommandBarLoadingStrip } from "./loading-state";
import { ConnectionStatus } from "./connection-status";
import { ErrorBoundary } from "./error-boundary";
import { HamburgerNav } from "./hamburger-nav";
import { MobileTradeSheet } from "./mobile-trade-sheet";
import { MobileBottomNav } from "./mobile-bottom-nav";
import { TradeConfirmModal } from "./trade-confirm-modal";
import { usePullToRefresh } from "../../hooks/use-pull-to-refresh";
import { PullToRefreshIndicator } from "../ui/pull-to-refresh-indicator";
import { IntelAccordion } from "./intel-accordion";
import { IntelPanelToggles } from "./intel-panel-toggles";
import { HealthDashboard } from "./health-dashboard";
import { PipelineDiagnosticsPanel } from "./pipeline-diagnostics-panel";
import { CombinedMenuButton } from "./combined-menu-button";
import { NotificationBell } from "./notification-bell";
import { LotSizeCalculator } from "./lot-size-calculator";
import { BridgeOfflineBanner } from "./bridge-offline-banner";
import { useBridgeAutoRetry } from "../../hooks/use-bridge-auto-retry";
import { TABS, type IntelPanelId, resolveEnabledPanels, readIntelPanelOverrides } from "../../lib/constants";
import { PriceChart } from "../charts/PriceChart";
import { CollapsiblePanel } from "../ui/collapsible-panel";

// Intelligence panels
import { MarketIntelligencePanel } from "../intelligence/MarketIntelligencePanel";
import { MultiTimeframePanel } from "../intelligence/MultiTimeframePanel";
import { EvidencePanel } from "../intelligence/EvidencePanel";
import { MarketThesisPanel } from "../intelligence/MarketThesisPanel";
import { ConfidenceBreakdownPanel } from "../intelligence/ConfidenceBreakdownPanel";
import { TradePlanPanel } from "../intelligence/TradePlanPanel";
import { AlternativeScenarioPanel } from "../intelligence/AlternativeScenarioPanel";
import { TradeProgressPanel } from "../intelligence/TradeProgressPanel";
import { ConfidenceTrendPanel } from "../intelligence/ConfidenceTrendPanel";
import { RiskAssessmentPanel } from "../intelligence/RiskAssessmentPanel";
import { ThesisInvalidationPanel } from "../intelligence/ThesisInvalidationPanel";
import { DecisionHistoryPanel } from "../intelligence/DecisionHistoryPanel";
import { TradeJournalDashboard } from "../intelligence/TradeJournalDashboard";
import { MissedTradeLearningPanel } from "../intelligence/MissedTradeLearningPanel";
import CurveFittingTestPanel from "../intelligence/CurveFittingTestPanel";
import { SystemPerformancePanel } from "../intelligence/SystemPerformancePanel";
import GeneratorFingerprintPanel from "../intelligence/GeneratorFingerprintPanel";

/** Shared intelligence tab content — used by both desktop section and mobile accordion. */
function IntelTabContent({
  tab,
  intelligence,
  call,
  history,
  loading,
}: {
  tab: "overview" | "analysis" | "history" | "learning";
  intelligence: ReturnType<typeof useOperatorWorkspace>["intelligence"];
  call: ReturnType<typeof useOperatorWorkspace>["currentCall"];
  history: ReturnType<typeof useOperatorWorkspace>["history"];
  loading?: boolean;
}) {
  switch (tab) {
    case "overview":
      return (
        <>
          <ConfidenceBreakdownPanel
            breakdown={intelligence?.confidence_breakdown || null}
            modelProbability={call?.confidence ?? undefined}
            loading={loading}
          />
          <CollapsiblePanel title="Missed Trade Learning">
            <MissedTradeLearningPanel
              data={intelligence?.missed_trade_learning ?? null}
              loading={loading}
            />
          </CollapsiblePanel>
          <CollapsiblePanel title="Alternative Scenario">
            <AlternativeScenarioPanel
              scenario={intelligence?.alternative_scenario || null}
              loading={loading}
            />
          </CollapsiblePanel>
        </>
      );
    case "analysis":
      return (
        <>
          <TradePlanPanel
            plan={intelligence?.trade_plan || null}
          />
          <div className="grid gap-5 md:grid-cols-2">
            <CollapsiblePanel title="Confidence Trend">
              <ConfidenceTrendPanel
                trend={intelligence?.confidence_trend || null}
                loading={loading}
              />
            </CollapsiblePanel>
            <RiskAssessmentPanel
              assessment={intelligence?.risk_assessment || null}
              loading={loading}
            />
          </div>
          <CollapsiblePanel title="Thesis Invalidation">
            <ThesisInvalidationPanel
              invalidation={intelligence?.thesis_invalidation || null}
              currentPrice={call?.current_close ?? null}
              loading={loading}
            />
          </CollapsiblePanel>
        </>
      );
    case "history":
      return (
        <>
          <CollapsiblePanel title="Trade Progress">
            <TradeProgressPanel
              progress={intelligence?.trade_progress || null}
              currentPrice={call?.current_close ?? null}
              loading={loading}
            />
          </CollapsiblePanel>
          <CollapsiblePanel title="Confidence Trend">
            <ConfidenceTrendPanel
              trend={intelligence?.confidence_trend || null}
              loading={loading}
            />
          </CollapsiblePanel>
          <CollapsiblePanel title="Decision History">
            <DecisionHistoryPanel
              history={history}
              loading={loading}
            />
          </CollapsiblePanel>
        </>
      );
    case "learning":
      return (
        <>
          <CollapsiblePanel title="Generator Fingerprint & EGARCH Calibration">
            <GeneratorFingerprintPanel
              data={intelligence?.generator_fingerprint ?? null}
              loading={loading}
            />
          </CollapsiblePanel>
          <CollapsiblePanel title="Curve-Fitting Test">
            {intelligence?.curve_fitting_test ? (
              <CurveFittingTestPanel data={intelligence.curve_fitting_test} />
            ) : (
              <div
                className="info-card"
                style={{ padding: "1.25rem", borderRadius: "0.75rem" }}
              >
                <div style={{ fontSize: "0.8125rem", fontWeight: 600, color: "var(--text-strong)", marginBottom: "0.375rem" }}>
                  Curve-Fitting Test
                </div>
                <p style={{ margin: 0, fontSize: "0.75rem", lineHeight: 1.5, color: "var(--text-body)" }}>
                  No curve-fitting report found. Run the synthetic backtest to generate one:
                </p>
                <pre
                  style={{
                    marginTop: "0.5rem",
                    padding: "0.5rem 0.75rem",
                    borderRadius: "0.375rem",
                    background: "var(--bg-panel-muted)",
                    fontSize: "0.6875rem",
                    fontFamily: "monospace",
                    color: "var(--text-body)",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-all",
                    margin: 0,
                  }}
                >{`python -m synthetic_trader backtest-synth --symbol R_100 --episodes 20 --ticks 5000 --prop-firm blueberry_2step --artifact-output data/curve_fitting_report.json`}</pre>
              </div>
            )}
          </CollapsiblePanel>
          <CollapsiblePanel title="System Performance">
            <SystemPerformancePanel
              performance={intelligence?.system_performance ?? null}
              loading={loading}
            />
          </CollapsiblePanel>
          <CollapsiblePanel title="Trade Journal">
            <TradeJournalDashboard
              externalTrades={null}
              confidenceTrend={intelligence?.confidence_trend ?? null}
            />
          </CollapsiblePanel>
        </>
      );
  }
}

function IntelLoadingBlock() {
  return (
    <div className="intelligence-panel surface rounded-[1.5rem] p-4">
      <div className="flex items-center gap-3">
        <div className="loading-pulse" aria-hidden="true" />
        <p className="text-sm text-[var(--text-body)]">Analyzing market structure…</p>
      </div>
    </div>
  );
}

export function OperatorShell() {
  const workspace = useOperatorWorkspace();
  const [intelligenceTab, setIntelligenceTab] = useState<"overview" | "analysis" | "history" | "learning">("overview");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [bottomSheetOpen, setBottomSheetOpen] = useState(false);
  const [intelAccordionOpen, setIntelAccordionOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  // Lazy initializer reads from localStorage to match saved theme on first render.
  // Wrapped in try/catch for SSR safety where localStorage is unavailable.
  const [currentTheme, setCurrentTheme] = useState(() => {
    try {
      return localStorage.getItem("data-theme") || "light";
    } catch {
      return "light";
    }
  });

  // Sync DOM attribute on mount only — other code reading
  // document.documentElement stays consistent. Toggle handler writes DOM directly.
  useEffect(() => {
    setMounted(true);
    try {
      document.documentElement.setAttribute("data-theme", currentTheme);
    } catch {
      // DOM unavailable — no-op
    }

    // Cross-tab theme sync: listen for storage changes so if the user
    // opens the app in two browser tabs and changes theme in one, the other updates.
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === "data-theme" && e.newValue) {
        setCurrentTheme(e.newValue);
        try {
          document.documentElement.setAttribute("data-theme", e.newValue);
        } catch {
          // DOM unavailable — no-op
        }
      }
    };
    window.addEventListener("storage", handleStorageChange);
    return () => window.removeEventListener("storage", handleStorageChange);
  }, []);

  // Intelligence panel visibility — initialised from localStorage overrides
  // merged with trading-mode defaults. Re-resolves when trading mode changes.
  const [enabledPanels, setEnabledPanels] = useState<IntelPanelId[]>(() =>
    resolveEnabledPanels(workspace.tradingMode, readIntelPanelOverrides()),
  );

  const isLoading = workspace.loading;
  const isDesktop = useMediaQuery("(min-width: 768px)");

  // Auto-retry bridge reconnection with exponential backoff
  const bridgeOffline = workspace.currentCall?.guardian_state === "unavailable" && !isLoading;
  const bridgeAutoRetry = useBridgeAutoRetry({
    offline: bridgeOffline,
    loading: isLoading,
    onRetry: () => workspace.runSymbol(workspace.activeSymbol),
    baseDelayMs: 30_000,   // 30 seconds
    maxDelayMs: 300_000,   // 5 minutes max
    maxAttempts: 0,         // unlimited
  });

  // Re-resolve panels when trading mode changes
  useEffect(() => {
    setEnabledPanels(
      resolveEnabledPanels(workspace.tradingMode, readIntelPanelOverrides()),
    );
  }, [workspace.tradingMode]);

  // Persist panel toggle changes to state and localStorage is handled by the component
  const handlePanelToggleChange = (updated: IntelPanelId[]) => {
    setEnabledPanels(updated);
  };

  // Close mobile nav on resize to desktop
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth >= 768) {
        setMobileNavOpen(false);
        setBottomSheetOpen(false);
      }
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // Pull-to-refresh — only active on mobile and when not already loading
  const PULL_THRESHOLD = 80;
  const { pullDistance, isRefreshing, isThresholdReached, handlers: pullHandlers } = usePullToRefresh({
    threshold: PULL_THRESHOLD,
    onRefresh: () => {
      void workspace.runSymbol(workspace.activeSymbol);
    },
    enabled: !isDesktop && !isLoading,
  });
  const pullThreshold = PULL_THRESHOLD;

  return (
    <main className="app-shell" aria-busy={isLoading}>
      {/* ── Hamburger Nav (mobile only) ──────────────────────────── */}
      <div
        className="shell-frame mx-auto max-w-7xl px-4 py-4 md:px-6 md:py-6"
        {...(!isDesktop ? pullHandlers : {})}
      >
        {/* ── Header: hamburger LEFT, actions RIGHT (professional convention) ── */}
        <div className="sticky top-0 z-40 flex items-center justify-between mb-2 py-1 -mx-4 px-4 md:mx-0 md:px-0 bg-[var(--bg-canvas)] md:bg-transparent backdrop-blur-sm md:backdrop-blur-none">
          <CombinedMenuButton
            onOpenSettings={() => setMobileNavOpen(true)}
            onToggleTheme={() => {
              const html = document.documentElement;
              const current = html.getAttribute("data-theme") || "light";
              const next = current === "dark" ? "light" : "dark";
              html.setAttribute("data-theme", next);
              setCurrentTheme(next);
              try { localStorage.setItem("data-theme", next); } catch {}
            }}
            currentTheme={currentTheme}
          />
          <NotificationBell
            permission={workspace.notifications.permission}
            prefs={workspace.notifications.prefs}
            isSupported={workspace.notifications.isSupported}
            onEnable={workspace.notifications.enable}
            onTogglePref={workspace.notifications.togglePref}
          />
        </div>
        {/* Hidden HamburgerNav — renders settings drawer via portal */}
        <div className="sr-only" aria-hidden="true">
          <HamburgerNav
            open={mobileNavOpen}
            activeSymbol={workspace.activeSymbol}
            currentCall={workspace.currentCall}
            accountMode={workspace.accountMode}
            tradingMode={workspace.tradingMode}
            executionMode={workspace.executionMode}
            onOpen={() => setMobileNavOpen(true)}
            onClose={() => setMobileNavOpen(false)}
            onSetAccountMode={workspace.setAccountMode}
            onRequestPropMode={workspace.requestPropMode}
            onSetTradingMode={workspace.setTradingMode}
            onSetExecutionMode={workspace.setExecutionMode}
          />
        </div>

        {/* ── Pull-to-refresh indicator (mobile only) ────────────── */}
        {!isDesktop && (
          <PullToRefreshIndicator
            pullDistance={pullDistance}
            isRefreshing={isRefreshing}
            isThresholdReached={isThresholdReached}
            threshold={pullThreshold}
          />
        )}
        {/* ── Bridge Offline Banner ───────────────────────────────── */}
        {/* Only show after mounted to prevent SSR hydration flash.
            !isLoading prevents false positives from stale cached calls. */}
        {mounted && (
          <BridgeOfflineBanner
            offline={workspace.currentCall?.guardian_state === "unavailable" && !isLoading}
            onRetry={() => workspace.runSymbol(workspace.activeSymbol)}
            retrying={isLoading}
            autoRetryAttempt={bridgeAutoRetry.attempt}
            secondsUntilRetry={bridgeAutoRetry.secondsUntilRetry}
            autoRetryPaused={bridgeAutoRetry.paused}
            onPauseAutoRetry={bridgeAutoRetry.pause}
            onResumeAutoRetry={bridgeAutoRetry.resume}
          />
        )}

        {/* ── Connection Status ────────────────────────────────────── */}
        <ErrorBoundary label="Connection status">
          <ConnectionStatus
            autoRetryAttempt={bridgeAutoRetry.attempt}
            secondsUntilRetry={bridgeAutoRetry.secondsUntilRetry}
          />
        </ErrorBoundary>

        {/* ── Health Dashboard (collapsible) ─────────────────────────── */}
        <div className="mb-5">
          <ErrorBoundary label="System health">
            <HealthDashboard />
          </ErrorBoundary>
        </div>

        {/* ── Live Price Chart ─────────────────────────────────── */}
        <ErrorBoundary label="Live price chart">
          <PriceChart />
        </ErrorBoundary>

        {/* ── Command Bar ──────────────────────────────────────────── */}
        <CommandBar
          accountMode={workspace.accountMode}
          activeSymbol={workspace.activeSymbol}
          loading={isLoading}
          loadingElapsedSeconds={workspace.loadingElapsedSeconds}
          tradingMode={workspace.tradingMode}
          onRunSymbol={workspace.runSymbol}
          onRequestPropMode={workspace.requestPropMode}
          onSelectMode={workspace.setAccountMode}
          onSelectTradingMode={workspace.setTradingMode}
          onStopRefresh={workspace.stopRefresh}
        />

        {/* ── Prop Connection Modal ────────────────────────────────── */}
        <PropConnectionModal
          open={workspace.propConnectionDraftOpen}
          initialValue={workspace.propConnection}
          onCancel={workspace.cancelPropModeRequest}
          onConfirm={workspace.confirmPropMode}
        />

        {/* ── Command-bar loading strip ───────────────────────────── */}
        {isLoading && <div className="-mt-1 mb-1"><CommandBarLoadingStrip /></div>}

        {/* ── Intelligence Overview ────────────────────────────────── */}
        {isLoading ? (
          <SkeletonLoader />
        ) : workspace.currentCall ? (
          <section className="intelligence-stage mt-4 md:mt-5">
            {/* Panel visibility toggles */}
            <div className="flex items-center justify-end gap-3 mb-3">
              <IntelPanelToggles
                tradingMode={workspace.tradingMode}
                enabledPanels={enabledPanels}
                onChange={handlePanelToggleChange}
              />
            </div>

            <div className="grid gap-4">
            {workspace.intelligenceLoading ? (
              <>
                <IntelLoadingBlock />
                <div className="grid gap-4 md:grid-cols-2">
                  <IntelLoadingBlock />
                  <IntelLoadingBlock />
                </div>
                <IntelLoadingBlock />
              </>
            ) : (
              <>
                {enabledPanels.includes("market_intelligence") && (
                  <MarketIntelligencePanel
                    intelligence={workspace.intelligence?.market_intelligence ?? null}
                    currentPrice={workspace.currentCall?.current_close ?? null}
                    loading={workspace.intelligenceLoading}
                    garchCalibrated={workspace.intelligence?.garch_forecast?.calibrated}
                  />
                )}
                {(enabledPanels.includes("multi_timeframe") || enabledPanels.includes("evidence_summary")) && (
                  <div className="grid gap-4 md:grid-cols-2">
                    {enabledPanels.includes("multi_timeframe") && (
                      <MultiTimeframePanel
                        marketIntelligence={workspace.intelligence?.market_intelligence ?? null}
                        loading={workspace.intelligenceLoading}
                      />
                    )}
                    {enabledPanels.includes("evidence_summary") && (
                      <CollapsiblePanel title="Evidence Summary">
                        <EvidencePanel
                          evidence={workspace.intelligence?.evidence_summary ?? null}
                          loading={workspace.intelligenceLoading}
                        />
                      </CollapsiblePanel>
                    )}
                  </div>
                )}
                {enabledPanels.includes("market_thesis") && (
                  <CollapsiblePanel title="Market Thesis">
                    <MarketThesisPanel
                      thesis={(workspace.intelligence?.market_thesis ?? null) as any}
                      loading={workspace.intelligenceLoading}
                    />
                  </CollapsiblePanel>
                )}
              </>
            )}
            </div>
          </section>
        ) : null}

        {/* ── Core Decision ────────────────────────────────────────── */}
        <section className="decision-stage mt-6 grid gap-6 md:mt-7 xl:grid-cols-[1.45fr_0.85fr]">
          <PrimaryCallPanel
            call={workspace.currentCall}
            guardianStatus={workspace.guardianStatus}
            loading={isLoading}
            onRetry={() => workspace.runSymbol(workspace.activeSymbol)}
            retryLabel="Retry live read"
          />
          {/* Desktop: inline. Mobile: in bottom sheet. Conditionally rendered so neither DOM tree is mounted on the wrong viewport. */}
          {isDesktop && (
            <div className="desktop-trade-panel">
              <TradeInstructionPanel
                call={workspace.currentCall}
                guardianStatus={workspace.guardianStatus}
                trackedPosition={workspace.trackedPosition}
                executing={workspace.executing}
                executionMode={workspace.executionMode}
                onExecute={() => workspace.submitTradeOrder()}
                onClose={() => workspace.closeTrackedPosition()}
                onSetExecutionMode={workspace.setExecutionMode}
              />
            </div>
          )}
        </section>

        {/* ── Intelligence Deep Dive ────────────────────────────────── */}
        {!isLoading && isDesktop && workspace.currentCall && (
          <section className="intelligence-deep-dive mt-6 md:mt-7">
            {/* Desktop tabs */}
            <div className="desktop-intel-tabs flex items-center gap-1 border-b border-[var(--line-subtle)] pb-3 mb-5">
              {TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setIntelligenceTab(tab.id)}
                  className={`tab-button ${intelligenceTab === tab.id ? "tab-button--active" : ""}`}
                  aria-pressed={intelligenceTab === tab.id}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <div className="space-y-5">
              <IntelTabContent
                tab={intelligenceTab}
                intelligence={workspace.intelligence}
                call={workspace.currentCall}
                history={workspace.history}
                loading={workspace.intelligenceLoading}
              />
            </div>
          </section>
        )}

        {/* Mobile: collapsible accordion for intelligence deep dive */}
        {!isLoading && !isDesktop && workspace.currentCall && (
          <IntelAccordion
            open={intelAccordionOpen}
            activeTab={intelligenceTab}
            onToggle={setIntelAccordionOpen}
            onTabChange={setIntelligenceTab}
            renderContent={(tab) => (
              <IntelTabContent
                tab={tab}
                intelligence={workspace.intelligence}
                call={workspace.currentCall}
                history={workspace.history}
                loading={workspace.intelligenceLoading}
              />
            )}
          />
        )}

        {/* ── Support Stage ────────────────────────────────────────── */}
        <section className="support-stage mt-6 grid gap-6 md:mt-7 xl:grid-cols-[0.95fr_1.05fr]">
          {workspace.accountMode === "prop_firm" && workspace.propProfile ? (
            <div className="space-y-3">
              <p className="utility-copy text-xs uppercase tracking-[0.2em] text-[var(--text-label)]">
                {workspace.propProfile.telemetry.message}
              </p>
              <PropCompliancePanel
                call={workspace.propCallPreview}
                profile={workspace.propProfile}
              />
            </div>
          ) : null}
          <HistoryPanel history={workspace.history} />
        </section>
        {/* ── Lot Size Calculator ─────────────────────────────── */}
        <section className="mt-6">
          <ErrorBoundary label="Lot size calculator">
            <LotSizeCalculator
              accountEquity={workspace.propProfile?.currentBalance || 100_000}
              entryPrice={workspace.currentCall?.entry ?? null}
              stopLoss={workspace.currentCall?.stop_loss ?? null}
              takeProfit={workspace.currentCall?.take_profit ?? null}
              symbol={workspace.activeSymbol}
            />
          </ErrorBoundary>
        </section>

        {/* ── Pipeline Diagnostics ────────────────────────────────── */}
        <section className="mt-6">
          <ErrorBoundary label="Pipeline diagnostics">
            <PipelineDiagnosticsPanel />
          </ErrorBoundary>
        </section>
      </div>

      {/* ── Mobile Bottom Nav — replaces the standalone FAB ──────── */}
      {!isDesktop && (
        <MobileBottomNav
          activeTab={bottomSheetOpen ? "execute" : null}
          onExecute={() => setBottomSheetOpen(true)}
          onHistory={() => {
            setIntelAccordionOpen(true);
            setIntelligenceTab("history");
          }}
          onSettings={() => setMobileNavOpen(true)}
        />
      )}

      {/* ── Trade Confirmation Modal (replaces window.confirm) ──── */}
      {workspace.confirmModalOpen && workspace.currentCall && (
        <TradeConfirmModal
          open={workspace.confirmModalOpen}
          call={workspace.currentCall}
          executionMode={workspace.executionMode}
          executionError={workspace.executionError}
          onConfirm={workspace.confirmModalConfirm}
          onCancel={workspace.confirmModalCancel}
        />
      )}

      {/* ── Execution Success Toast ──────────────────────────── */}
      {workspace.executionSuccess && (
        <div
          className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[200] flex items-center gap-2.5 px-4 py-3 rounded-xl border border-[rgba(15,107,87,0.25)] bg-[rgba(15,107,87,0.12)] shadow-[0_8px_32px_rgba(0,0,0,0.12)] backdrop-blur-sm"
          style={{ animation: "toastSlideUp 300ms var(--ease-out)" }}
          role="alert"
        >
          <span className="text-[var(--accent-positive)] text-sm">✓</span>
          <span className="text-sm font-medium text-[var(--text-strong)]">
            {workspace.executionSuccess}
          </span>
        </div>
      )}

      {/* ── Mobile Trade Sheet (bottom sheet) ────────────────────── */}
      <MobileTradeSheet
        open={bottomSheetOpen}
        call={workspace.currentCall}
        guardianStatus={workspace.guardianStatus}
        trackedPosition={workspace.trackedPosition}
        executing={workspace.executing}
        executionMode={workspace.executionMode}
        onSubmitTrade={workspace.submitTradeOrder}
        onCloseTrade={workspace.closeTrackedPosition}
        onSetExecutionMode={workspace.setExecutionMode}
        onClose={() => setBottomSheetOpen(false)}
      />

      <style jsx global>{`
        @keyframes toastSlideUp {
          from {
            opacity: 0;
            transform: translateX(-50%) translateY(16px);
          }
          to {
            opacity: 1;
            transform: translateX(-50%) translateY(0);
          }
        }
      `}</style>
    </main>
  );
}
