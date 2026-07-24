"use client"

import type { TradePlan } from "../../lib/contracts";
import { formatPrice } from "../../lib/formatters";

type TradePlanPanelProps = {
  plan: TradePlan | null;
};

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
        <span className={`info-chip rounded-full px-3 py-1 text-sm font-medium ${plan.direction === "long" ? "text-[var(--accent-positive)] bg-[var(--accent-positive-soft)]" : "text-[var(--accent-danger)] bg-[var(--accent-danger-soft)]"}`}>
          {plan.direction.toUpperCase()}
        </span>
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
