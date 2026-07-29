"use client";

import { useState } from "react";
import type { TradePlan } from "../../lib/contracts";
import { formatPrice } from "../../lib/formatters";

type TradePlanPanelProps = {
  plan: TradePlan | null;
};

function CopyToMt5Button({ plan }: { plan: TradePlan }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const entry = plan.executionLevels?.entry ?? plan.entry;
    const sl = plan.executionLevels?.executionStop ?? plan.executionStop;
    const tp = plan.executionLevels?.primaryTarget ?? plan.primaryTarget;
    const direction = plan.direction === "long" ? "BUY" : "SELL";
    const orderType = plan.direction === "long" ? "Buy Limit" : "Sell Limit";

    const text = [
      `${direction} ${orderType}`,
      `Entry: ${entry ? formatPrice(entry) : "—"}`,
      `Stop Loss: ${sl ? formatPrice(sl) : "—"}`,
      `Take Profit: ${tp ? formatPrice(tp) : "—"}`,
      `Hold: ${plan.holdHorizonMinutes} min`,
      `R:R: ${plan.rewardRisk != null ? `1:${plan.rewardRisk.toFixed(1)}` : "—"}`,
    ].join("\n");

    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for older browsers
      try {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        document.body.removeChild(textarea);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch {
        // Both methods failed — don't show false positive
      }
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label="Copy trade levels to clipboard for MT5"
      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[10px] font-medium transition-all ${
        copied
          ? "border-[var(--accent-positive)] text-[var(--accent-positive)] bg-[var(--accent-positive-soft)]"
          : "border-[var(--accent-ink)] text-[var(--accent-ink)] hover:bg-[var(--accent-ink)] hover:text-white"
      }`}
    >
      {copied ? (
        <>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polyline points="20 6 9 17 4 12" />
          </svg>
          Copied!
        </>
      ) : (
        <>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
          </svg>
          Copy to MT5
        </>
      )}
    </button>
  );
}

export function TradePlanPanel({ plan }: TradePlanPanelProps) {
  if (!plan) {
    return (
      <section className="intelligence-panel surface rounded-[1.5rem] p-4">
        <p className="utility-copy text-xs uppercase tracking-[0.2em]">Primary Trade Plan</p>
        <p className="mt-4 text-base text-[var(--text-body)]">No active trade plan. Run a live read to generate a plan.</p>
      </section>
    );
  }

  return (
    <section className="intelligence-panel surface rounded-[1.5rem] p-4">
      <div className="flex items-center justify-between">
        <p className="utility-copy text-xs uppercase tracking-[0.2em]">Primary Trade Plan</p>
        <div className="flex items-center gap-2">
          <CopyToMt5Button plan={plan} />
          <span className={`info-chip rounded-full px-3 py-1 text-sm font-medium ${plan.direction === "long" ? "text-[var(--accent-positive)] bg-[var(--accent-positive-soft)]" : "text-[var(--accent-danger)] bg-[var(--accent-danger-soft)]"}`}>
            {plan.direction.toUpperCase()}
          </span>
        </div>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-4">
        <DetailCard title="Entry" value={formatPrice(plan.entry)} hint="Limit order at trigger" />
        <DetailCard title="Execution Stop" value={formatPrice(plan.executionStop)} hint="Invalidates entry logic" />
        <DetailCard title="Thesis Invalidation" value={plan.thesisInvalidation ? formatPrice(plan.thesisInvalidation) : "—"} hint="Full thesis invalidation" />
        <DetailCard title="R:R" value={plan.rewardRisk != null ? plan.rewardRisk.toFixed(2) : "—"} hint="Reward to risk ratio" />
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <DetailCard title="Primary Target" value={formatPrice(plan.primaryTarget)} hint={`R:R ${(plan.primaryTarget && plan.entry && plan.executionStop ? ((plan.primaryTarget - plan.entry) / Math.abs(plan.entry - plan.executionStop)).toFixed(2) : "—")}`} />
        <DetailCard title="Extended Target" value={plan.extendedTarget ? formatPrice(plan.extendedTarget) : "—"} hint="Extended objective if momentum continues" />
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-3">
        <DetailCard title="Hold Horizon" value={`${plan.holdHorizonMinutes} min`} hint="Max expected hold time" />
        <DetailCard title="Trigger Type" value={plan.triggerType || "Pattern"} hint="Entry trigger method" />
        <DetailCard title="R:R" value={plan.rewardRisk != null ? plan.rewardRisk.toFixed(2) : "—"} hint="Reward to risk" />
      </div>

      <div className="mt-4 p-4 rounded-lg bg-[var(--accent-neutral-soft)] border border-[var(--accent-neutral-soft)]">
        <p className="utility-copy text-xs uppercase tracking-[0.2em] text-[var(--accent-neutral)] mb-2">Thesis</p>
        <p className="text-sm" style={{ color: "var(--text-body)" }}>{plan.thesis}</p>
      </div>

      <div className="mt-4 p-4 rounded-lg bg-[var(--accent-danger-soft)] border border-[var(--accent-danger-soft)]">
        <p className="utility-copy text-xs uppercase tracking-[0.2em] text-[var(--accent-danger)] mb-1">Invalidation</p>
        <p className="text-sm" style={{ color: "var(--accent-danger)" }}>{plan.invalidationReason}</p>
      </div>

      <div className="mt-4">
        <p className="utility-copy text-xs uppercase tracking-[0.2em] text-[var(--accent-neutral)] mb-2">Execution Levels</p>
        <dl className="grid gap-3 md:grid-cols-5">
          <ExecutionLevel label="Entry" value={plan.executionLevels?.entry ? formatPrice(plan.executionLevels.entry) : "—"} />
          <ExecutionLevel label="Execution Stop" value={plan.executionLevels?.executionStop ? formatPrice(plan.executionLevels.executionStop) : "—"} />
          <ExecutionLevel label="Primary Target" value={plan.executionLevels?.primaryTarget ? formatPrice(plan.executionLevels.primaryTarget) : "—"} />
          <ExecutionLevel label="Extended Target" value={plan.executionLevels?.extendedTarget ? formatPrice(plan.executionLevels.extendedTarget) : "—"} />
          <ExecutionLevel label="Thesis Invalidation" value={plan.executionLevels?.thesisInvalidation ? formatPrice(plan.executionLevels.thesisInvalidation) : "—"} />
        </dl>
      </div>
    </section>
  );
}

function DetailCard({ title, value, hint }: { title: string; value: string; hint?: string }) {
  return (
    <div className="info-card rounded-[1rem] p-4">
      <p className="utility-copy text-xs uppercase tracking-[0.2em] text-[var(--text-label)]">{title}</p>
      <p className="mt-2 text-base font-semibold text-[var(--text-strong)]">{value}</p>
      {hint && <p className="mt-1 text-xs text-[var(--text-muted)]">{hint}</p>}
    </div>
  );
}

function ExecutionLevel({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="utility-copy text-xs uppercase tracking-[0.1em] text-[var(--text-label)]">{label}</dt>
      <dd className="text-base font-semibold text-[var(--text-strong)]">{value}</dd>
    </div>
  );
}
