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
import { NotificationBell } from "./notification-bell";
import { TABS, type IntelPanelId, resolveEnabledPanels, readIntelPanelOverrides } from "../../lib/constants";
import { PriceChart } from "../charts/PriceChart";

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
          <AlternativeScenarioPanel
            scenario={intelligence?.alternative_scenario || null}
          />
        </>
      );
    case "analysis":
      return (
        <>
          <TradePlanPanel
            plan={intelligence?.trade_plan || null}
          />
          <div className="grid gap-5 md:grid-cols-2">
            <ConfidenceTrendPanel
              trend={intelligence?.confidence_trend || null}
            />
            <RiskAssessmentPanel
              assessment={intelligence?.risk_assessment || null}
            />
          </div>
          <ThesisInvalidationPanel
            invalidation={intelligence?.thesis_invalidation || null}
            currentPrice={call?.current_close ?? null}
          />
        </>
      );
    case "history":
      return (
        <>
          <TradeProgressPanel
            progress={intelligence?.trade_progress || null}
            currentPrice={call?.current_close ?? null}
          />
          <ConfidenceTrendPanel
            trend={intelligence?.confidence_trend || null}
          />
          <DecisionHistoryPanel
            history={history}
          />
        </>
      );
    case "learning":
      return (
        <TradeJournalDashboard
          externalTrades={null}
          confidenceTrend={intelligence?.confidence_trend ?? null}
        />
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

  // Intelligence panel visibility — initialised from localStorage overrides
  // merged with trading-mode defaults. Re-resolves when trading mode changes.
  const [enabledPanels, setEnabledPanels] = useState<IntelPanelId[]>(() =>
    resolveEnabledPanels(workspace.tradingMode, readIntelPanelOverrides()),
  );

  const isLoading = workspace.loading;
  const isDesktop = useMediaQuery("(min-width: 768px)");

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

      <div
        className="shell-frame mx-auto max-w-7xl px-4 py-4 md:px-6 md:py-6"
        {...(!isDesktop ? pullHandlers : {})}
      >
        {/* ── Notification bell ──────────────────────────────────── */}
        <div className="flex items-center justify-end mb-2">
          <NotificationBell
            permission={workspace.notifications.permission}
            prefs={workspace.notifications.prefs}
            isSupported={workspace.notifications.isSupported}
            onEnable={workspace.notifications.enable}
            onTogglePref={workspace.notifications.togglePref}
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
        {/* ── Connection Status ────────────────────────────────────── */}
        <ErrorBoundary label="Connection status">
          <ConnectionStatus />
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
                      <EvidencePanel
                        evidence={workspace.intelligence?.evidence_summary ?? null}
                        loading={workspace.intelligenceLoading}
                      />
                    )}
                  </div>
                )}
                {enabledPanels.includes("market_thesis") && (
                  <MarketThesisPanel
                    thesis={(workspace.intelligence?.market_thesis ?? null) as any}
                    loading={workspace.intelligenceLoading}
                  />
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
    </main>
  );
}
