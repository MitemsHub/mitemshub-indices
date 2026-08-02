/** Intelligence deep-dive tab identifiers. */
export type IntelTab = "overview" | "analysis" | "history" | "learning";

/** Shared tab configuration used by both the desktop tab bar and the mobile accordion. */
export const TABS: { id: IntelTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "analysis", label: "Analysis" },
  { id: "history", label: "History" },
  { id: "learning", label: "Learning" },
];

// ── Intelligence Panel Feature Flags ────────────────────────────────────
// Each panel has a unique ID, a human-readable label, a short description,
// and a default enabled-state per trading mode. Users can override the
// default from the command bar's settings dropdown.

export type IntelPanelId =
  | "market_intelligence"
  | "multi_timeframe"
  | "evidence_summary"
  | "market_thesis";

export type IntelPanelFlag = {
  id: IntelPanelId;
  label: string;
  description: string;
};

/** Default enabled panels per trading mode. Sniper shows everything. */
export const INTEL_PANEL_DEFAULTS: Record<string, IntelPanelId[]> = {
  sniper: ["market_intelligence", "multi_timeframe", "evidence_summary", "market_thesis"],
};

export const INTEL_PANELS: IntelPanelFlag[] = [
  {
    id: "market_intelligence",
    label: "Market Intelligence",
    description: "Current price, structure bias, trend direction, volatility state, and advanced metrics (Hurst, entropy, displacement).",
  },
  {
    id: "multi_timeframe",
    label: "Multi-Timeframe",
    description: "4H → 1H → 15M structure alignment, regime consistency, and confluence scoring across every analysed timeframe.",
  },
  {
    id: "evidence_summary",
    label: "Bullish vs Bearish Evidence",
    description: "Structured list of supporting and contradicting evidence grouped by source: structure, regime, momentum, volatility.",
  },
  {
    id: "market_thesis",
    label: "Current Market Thesis",
    description: "Consolidated directional thesis with invalidation levels, primary & extended targets, and key/counter evidence.",
  },
];

const STORAGE_KEY = "mitems-intel-panel-overrides";

type StoredOverrides = Record<string, IntelPanelId[]>;

/** Read per-trading-mode panel overrides from localStorage. */
export function readIntelPanelOverrides(): StoredOverrides {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    return JSON.parse(raw) as StoredOverrides;
  } catch {
    return {};
  }
}

/** Persist per-trading-mode panel overrides to localStorage. */
export function writeIntelPanelOverrides(overrides: StoredOverrides): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides));
  } catch {
    // localStorage may be unavailable
  }
}

/** Compute the set of enabled panel IDs for a given trading mode,
 * merging stored overrides on top of the mode defaults. */
export function resolveEnabledPanels(
  tradingMode: string,
  storedOverrides: StoredOverrides,
): IntelPanelId[] {
  const defaults = INTEL_PANEL_DEFAULTS[tradingMode] ?? INTEL_PANEL_DEFAULTS.sniper;
  const overrides = storedOverrides[tradingMode];
  if (!overrides) return defaults;
  // Only return valid panel IDs
  const validIds = new Set<IntelPanelId>([
    "market_intelligence",
    "multi_timeframe",
    "evidence_summary",
    "market_thesis",
  ]);
  return overrides.filter((id): id is IntelPanelId => validIds.has(id));
}
