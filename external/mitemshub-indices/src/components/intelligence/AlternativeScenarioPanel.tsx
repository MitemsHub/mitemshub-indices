"use client"

import type { AlternativeScenario } from "../../lib/contracts";
import { DataFreshnessDot } from "./DataFreshnessDot";
import { formatPct } from "../../lib/formatters";
import { AlternativeScenarioSkeleton } from "./AlternativeScenarioSkeleton";

type AlternativeScenarioPanelProps = {
  scenario: AlternativeScenario | null;
  loading?: boolean;
};

export function AlternativeScenarioPanel({ scenario, loading }: AlternativeScenarioPanelProps) {
  if (loading) {
    return <AlternativeScenarioSkeleton />;
  }

  if (!scenario) {
    return (
      <div className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
        <div className="flex items-center gap-2">
          <DataFreshnessDot live={false} />
          <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">Alternative Scenario</p>
        </div>
        <p className="mt-4 text-sm text-[var(--text-body)]">No alternative scenario available. Run a live read to generate.</p>
      </div>
    );
  }

  return (
    <div className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <DataFreshnessDot live={true} />
          <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">Alternative Scenario</p>
        </div>
        <span className="info-chip rounded-full px-2 md:px-3 py-0.5 md:py-1 text-xs md:text-sm">
          Probability: {formatPct(scenario.probability)}
        </span>
      </div>

      <div className="mt-3 md:mt-4 p-3 md:p-4 rounded-lg bg-gray-50 border border-gray-200">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-gray-500 mb-1.5 md:mb-2">Scenario</p>
        <p className="text-sm md:text-base font-medium text-gray-900">{scenario.scenario}</p>
      </div>

      <div className="mt-3 md:mt-4 p-3 md:p-4 rounded-lg bg-blue-50 border border-blue-200">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-blue-700 mb-1.5 md:mb-2">Description</p>
        <p className="text-sm md:text-base text-blue-800">{scenario.description}</p>
      </div>

      <div className="mt-3 md:mt-4 p-3 md:p-4 rounded-lg bg-amber-50 border border-amber-200">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.1em] text-amber-700 mb-1.5 md:mb-2">What Would Need to Change</p>
        <p className="text-sm md:text-base text-amber-800">{scenario.what_would_change}</p>
      </div>

      <div className="mt-3 md:mt-4 p-3 md:p-4 rounded-lg bg-gray-50 border border-gray-200">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.1em] text-gray-500 mb-1.5 md:mb-2">Trigger Condition</p>
        <p className="text-sm md:text-base text-gray-700">{scenario.trigger_condition}</p>
      </div>

      <div className="mt-3 md:mt-4 p-3 md:p-4 rounded-lg bg-blue-50 border border-blue-200">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.1em] text-blue-700 mb-1.5 md:mb-2">Probability Assessment</p>
        <div className="flex items-center gap-3 md:gap-4">
          <div className="flex-1">
            <div className="w-full h-2.5 md:h-3 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full bg-blue-500" style={{ width: `${scenario.probability * 100}%` }} />
            </div>
            <p className="mt-1 text-xs md:text-sm text-gray-600">Probability: {formatPct(scenario.probability)}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
