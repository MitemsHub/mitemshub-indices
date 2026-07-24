"use client"

import type { EvidenceSummary, Evidence } from "../../lib/contracts";

type EvidencePanelProps = {
  evidence: EvidenceSummary | null;
};

export function EvidencePanel({ evidence }: EvidencePanelProps) {
  if (!evidence) {
    return (
      <section className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">Bullish vs Bearish Evidence</p>
        <p className="mt-4 text-sm text-[var(--text-body)]">Evidence analysis is not available for the current call state.</p>
      </section>
    );
  }

  const allEvidence = [
    ...evidence.bullish.map((e) => ({ ...e, type: "bullish" as const })),
    ...evidence.bearish.map((e) => ({ ...e, type: "bearish" as const })),
    ...evidence.neutral.map((e) => ({ ...e, type: "neutral" as const })),
  ].sort((a, b) => b.strength - a.strength);

  return (
    <section className="intelligence-panel surface rounded-[1.5rem] p-3 md:p-4">
      <div className="flex items-center justify-between">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em]">Bullish vs Bearish Evidence</p>
        <div className="flex items-center gap-2 md:gap-3">
          <div className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 md:w-3 md:h-3 rounded-full bg-[var(--accent-positive)]" />
            <span className="text-xs md:text-sm font-medium text-[var(--accent-positive)]">{evidence.bullish.length}</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 md:w-3 md:h-3 rounded-full bg-[var(--accent-danger)]" />
            <span className="text-xs md:text-sm font-medium text-[var(--accent-danger)]">{evidence.bearish.length}</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 md:w-3 md:h-3 rounded-full bg-[var(--accent-neutral)]" />
            <span className="text-xs md:text-sm font-medium text-[var(--accent-neutral)]">{evidence.neutral.length}</span>
          </div>
        </div>
      </div>

      {/* Net score bar */}
      <div className="mt-3 md:mt-4">
        <div className="flex items-center gap-3 md:gap-4 text-xs md:text-sm">
          <div className="flex items-center gap-2">
            <div className="w-8 md:w-10 h-2 bg-[var(--accent-positive-soft)] rounded-full overflow-hidden">
              <div className="h-full bg-[var(--accent-positive)]" style={{ width: `${Math.max(0, evidence.net_score) * 50}%` }} />
            </div>
            <span className="text-[var(--accent-positive)] font-medium">{Math.max(0, evidence.net_score * 100).toFixed(0)}%</span>
          </div>
          <div className="w-px h-5 md:h-6 bg-[var(--line-subtle)]" />
          <div className="flex items-center gap-2">
            <div className="w-8 md:w-10 h-2 bg-[var(--accent-danger-soft)] rounded-full overflow-hidden">
              <div className="h-full bg-[var(--accent-danger)]" style={{ width: `${Math.max(0, -evidence.net_score) * 50}%` }} />
            </div>
            <span className="text-[var(--accent-danger)] font-medium">{Math.max(0, -evidence.net_score * 100).toFixed(0)}%</span>
          </div>
        </div>
      </div>

      <div className="mt-3 md:mt-4">
        <p className="utility-copy text-[10px] md:text-xs uppercase tracking-[0.2em] text-[var(--accent-neutral)] mb-2 md:mb-3">All Evidence (ranked by strength)</p>
        <div className="space-y-1.5 md:space-y-2">
          {allEvidence.map((item, index) => (
            <EvidenceRow key={`${item.type}-${index}`} item={item} rank={index + 1} />
          ))}
        </div>
      </div>
    </section>
  );
}

function EvidenceRow({ item, rank }: { item: Evidence; rank: number }) {
  const typeColors: Record<string, string> = {
    bullish: "bg-[var(--accent-positive-soft)] border-[var(--accent-positive-soft)]",
    bearish: "bg-[var(--accent-danger-soft)] border-[var(--accent-danger-soft)]",
    neutral: "bg-[var(--accent-neutral-soft)] border-[var(--accent-neutral-soft)]",
    supporting: "bg-[var(--accent-ink-soft)] border-[var(--accent-ink-soft)]",
    contradicting: "bg-[var(--accent-warn-soft)] border-[var(--accent-warn-soft)]",
  };

  const typeTextColors: Record<string, string> = {
    bullish: "text-[var(--accent-positive)]",
    bearish: "text-[var(--accent-danger)]",
    neutral: "text-[var(--accent-neutral)]",
    supporting: "text-[var(--accent-ink)]",
    contradicting: "text-[var(--accent-warn)]",
  };

  const typeIcons: Record<string, string> = {
    bullish: "▲",
    bearish: "▼",
    neutral: "■",
    supporting: "+",
    contradicting: "−",
  };

  return (
    <div className={`p-2 md:p-3 rounded-lg border ${typeColors[item.type] || "bg-[var(--accent-neutral-soft)] border-[var(--accent-neutral-soft)]"}`}>
      {/* Mobile: two-row stacked layout */}
      <div className="flex items-center gap-2 md:gap-3">
        {/* Rank + type icon — stacked vertically on mobile, inline on desktop */}
        <div className="flex md:hidden flex-col items-center gap-0 flex-shrink-0">
          <span className="w-4 h-4 rounded-full bg-[var(--accent-neutral-soft)] flex items-center justify-center text-[8px] font-bold text-[var(--accent-neutral)]">{rank}</span>
          <span className={`w-4 h-4 rounded-full bg-[var(--accent-neutral-soft)] flex items-center justify-center text-[8px] font-bold ${typeTextColors[item.type] || "text-[var(--accent-neutral)]"}`}>
            {typeIcons[item.type]}
          </span>
        </div>
        {/* Desktop: inline rank + icon */}
        <div className="hidden md:flex items-center gap-2 flex-shrink-0">
          <span className="w-6 text-center text-xs font-bold text-[var(--accent-neutral)]">{rank}</span>
          <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${typeTextColors[item.type] || "text-[var(--accent-neutral)]"}`}>
            {typeIcons[item.type]}
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs md:text-sm font-medium" style={{ color: "var(--text-strong)" }}>{item.factor}</p>
          <p className="text-[10px] md:text-xs text-[var(--accent-neutral)] mt-0.5">{item.description}</p>
        </div>
        {/* Desktop: inline strength bar */}
        <div className="hidden md:flex items-center gap-2 text-xs text-[var(--accent-neutral)] flex-shrink-0">
          <div className="w-20 h-1.5 bg-[var(--accent-neutral-soft)] rounded-full overflow-hidden">
            <div className="h-full bg-[var(--accent-neutral)] rounded-full" style={{ width: `${item.strength * 100}%` }} />
          </div>
          <span className="font-mono font-medium w-9 text-right" style={{ color: "var(--text-strong)" }}>{Math.round(item.strength * 100)}%</span>
        </div>
      </div>
      {/* Mobile: prominent strength bar below */}
      <div className="md:hidden mt-2 ml-6">
        <div className="flex items-center gap-2">
          <div className="flex-1 h-1.5 md:h-2 bg-[var(--accent-neutral-soft)] rounded-full overflow-hidden">
            <div className="h-full bg-[var(--accent-neutral)] rounded-full transition-[width] duration-300" style={{ width: `${item.strength * 100}%` }} />
          </div>
          <span className="font-mono text-xs md:text-sm font-semibold tabular-nums flex-shrink-0" style={{ color: "var(--text-strong)" }}>{Math.round(item.strength * 100)}%</span>
        </div>
      </div>
    </div>
  );
}
