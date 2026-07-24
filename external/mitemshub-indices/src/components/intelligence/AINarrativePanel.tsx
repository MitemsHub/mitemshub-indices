"use client"

import type { AINarrative } from "../../lib/contracts";

type AINarrativePanelProps = {
  narrative: AINarrative | null;
};

export function AINarrativePanel({ narrative }: AINarrativePanelProps) {
  if (!narrative) {
    return (
      <div className="intelligence-panel surface rounded-[1.5rem] p-4">
        <p className="utility-copy text-xs uppercase tracking-[0.2em]">AI Narrative</p>
        <p className="mt-4 text-base text-[var(--text-body)]">Run a live read to generate AI narrative.</p>
      </div>
    );
  }

  return (
    <div className="intelligence-panel surface rounded-[1.5rem] p-4">
      <p className="utility-copy text-xs uppercase tracking-[0.2em]">AI Narrative</p>

      <div className="mt-4 space-y-5">
        <NarrativeSection title="Executive Summary" content={narrative.summary} icon="📋" />
        <NarrativeSection title="Market Context" content={narrative.market_context} icon="🌍" />
        <NarrativeSection title="Thesis" content={narrative.thesis} icon="🎯" />

        <div className="p-4 rounded-lg bg-[var(--accent-ink-soft)] border border-[var(--accent-ink-soft)]">
          <p className="utility-copy text-xs uppercase tracking-[0.2em] text-[var(--accent-ink)] mb-2">Key Drivers</p>
            <ul className="space-y-2 text-sm" style={{ color: "var(--text-strong)" }}>
              {(narrative.key_drivers || []).map((driver, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="flex-shrink-0 w-5 h-5 rounded-full bg-[var(--accent-ink)] text-white text-xs flex items-center justify-center mt-0.5">✓</span>
                  <span>{driver}</span>
                </li>
              ))}
            </ul>
        </div>

        <div className="p-4 rounded-lg bg-[var(--accent-warn-soft)] border border-[var(--accent-warn-soft)]">
          <p className="utility-copy text-xs uppercase tracking-[0.1em] text-[var(--accent-warn)] mb-2">Uncertainties & Risks</p>
            <ul className="space-y-2 text-sm" style={{ color: "var(--text-strong)" }}>
              {(narrative.uncertainties || []).map((uncertainty, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="flex-shrink-0 w-5 h-5 rounded-full bg-[var(--accent-warn)] text-white text-xs flex items-center justify-center mt-0.5">⚠</span>
                  <span>{uncertainty}</span>
                </li>
              ))}
            </ul>
        </div>

         <div className="p-4 rounded-lg bg-[var(--accent-neutral-soft)] border border-[var(--accent-neutral-soft)]">
           <p className="utility-copy text-xs uppercase tracking-[0.2em] text-[var(--accent-neutral)] mb-3">Scenario Analysis</p>
           <div className="grid gap-3 md:grid-cols-3">
             <ScenarioCard title="Base Case" content={narrative.scenario_analysis?.base_case || "No base case available"} color="blue" />
             <ScenarioCard title="Bull Case" content={narrative.scenario_analysis?.bull_case || "No bull case available"} color="green" />
             <ScenarioCard title="Bear Case" content={narrative.scenario_analysis?.bear_case || "No bear case available"} color="red" />
           </div>
         </div>

        <div className="p-4 rounded-lg bg-[var(--accent-positive-soft)] border border-[var(--accent-positive-soft)]">
          <p className="utility-copy text-xs uppercase tracking-[0.2em] text-[var(--accent-positive)] mb-2">Recommendation</p>
          <p className="text-base font-medium" style={{ color: "var(--text-strong)" }}>{narrative.recommendation}</p>
          <p className="mt-2 text-sm" style={{ color: "var(--accent-positive)" }}>{narrative.confidence_rationale}</p>
        </div>
      </div>
    </div>
  );
}

function NarrativeSection({
  title,
  content,
  icon,
}: {
  title: string;
  content: string;
  icon: string;
}) {
  return (
    <div className="p-4 rounded-lg bg-[var(--accent-neutral-soft)] border border-[var(--accent-neutral-soft)]">
      <div className="flex items-start gap-3">
        <span className="flex-shrink-0 w-8 h-8 rounded-full bg-[var(--bg-panel)] flex items-center justify-center text-base">{icon}</span>
        <div>
          <p className="utility-copy text-xs uppercase tracking-[0.2em] text-[var(--accent-neutral)] mb-1">{title}</p>
          <p className="text-base" style={{ color: "var(--text-strong)" }}>{content}</p>
        </div>
      </div>
    </div>
  );
}

function ScenarioCard({
  title,
  content,
  color,
}: {
  title: string;
  content: string;
  color: "blue" | "green" | "red";
}) {
  const colors: Record<string, string> = {
    blue: "bg-[var(--accent-ink-soft)] border-[var(--accent-ink-soft)]",
    green: "bg-[var(--accent-positive-soft)] border-[var(--accent-positive-soft)]",
    red: "bg-[var(--accent-danger-soft)] border-[var(--accent-danger-soft)]",
  };

  const textColors: Record<string, string> = {
    blue: "text-[var(--accent-ink)]",
    green: "text-[var(--accent-positive)]",
    red: "text-[var(--accent-danger)]",
  };

  return (
    <div className={`p-4 rounded-lg border ${colors[color]} ${textColors[color]}`}>
      <p className="utility-copy text-xs uppercase tracking-[0.2em] mb-2">{title}</p>
      <p className="text-sm" style={{ color: "var(--text-body)" }}>{content}</p>
    </div>
  );
}
