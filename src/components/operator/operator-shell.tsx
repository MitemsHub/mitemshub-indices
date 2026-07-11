"use client";

import React from "react";
import { useOperatorWorkspace } from "../../hooks/use-operator-workspace";
import { CommandBar } from "./command-bar";
import { HistoryPanel } from "./history-panel";
import { PrimaryCallPanel } from "./primary-call-panel";
import { PropConnectionModal } from "./prop-connection-modal";
import { PropCompliancePanel } from "./prop-compliance-panel";
import { ReviewSystemPanel } from "./review-system-panel";
import { TradeInstructionPanel } from "./trade-instruction-panel";

export function OperatorShell() {
  const workspace = useOperatorWorkspace();

  return (
    <main className="app-shell" aria-busy={workspace.loading}>
      <div className="shell-frame mx-auto max-w-7xl px-6 py-6">
        <CommandBar
          accountMode={workspace.accountMode}
          loading={workspace.loading}
          loadingElapsedSeconds={workspace.loadingElapsedSeconds}
          onRunSymbol={workspace.runSymbol}
          onRequestPropMode={workspace.requestPropMode}
          onSelectMode={workspace.setAccountMode}
        />

        <PropConnectionModal
          open={workspace.propConnectionDraftOpen}
          initialValue={workspace.propConnection}
          onCancel={workspace.cancelPropModeRequest}
          onConfirm={workspace.confirmPropMode}
        />

        <section className="decision-stage mt-6 grid gap-6 xl:grid-cols-[1.45fr_0.85fr]">
          <PrimaryCallPanel
            call={workspace.currentCall}
            guardianStatus={workspace.guardianStatus}
            loading={workspace.loading}
          />
          <TradeInstructionPanel
            call={workspace.currentCall}
            guardianStatus={workspace.guardianStatus}
          />

        </section>

        <section className="support-stage mt-6 grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
          {workspace.accountMode === "prop_firm" ? (
            <div className="space-y-3">
              <p className="utility-copy text-xs uppercase tracking-[0.2em]">
                {workspace.propProfile.telemetry.message}
              </p>
              <PropCompliancePanel
                call={workspace.propCallPreview}
                profile={workspace.propProfile}
              />
            </div>
          ) : (
            <ReviewSystemPanel status={workspace.systemStatus} />
          )}
          <HistoryPanel history={workspace.history} />
        </section>
      </div>
    </main>
  );
}
