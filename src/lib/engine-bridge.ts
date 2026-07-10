import { execFile } from "node:child_process";
import { appendFile, mkdir, readFile } from "node:fs/promises";
import { dirname } from "node:path";
import { promisify } from "node:util";
import {
  freshCallResponseSchema,
  type AccountMode,
  type FreshCallResponse,
  type PropConnectionInput,
  type PropProfileResponse,
  type PropProfileRequest,
} from "./contracts";
import {
  latestMockCall,
  mockCurrentPropProfile,
  mockSystemStatus,
  recentMockHistory,
} from "./mock-data";
import { evaluatePropCompliance, type PropAccountState } from "./prop-policy";

type SymbolCode = FreshCallResponse["symbol"];
type BaseFreshCall = Omit<
  FreshCallResponse,
  | "account_mode"
  | "prop_compliance"
  | "prop_adjusted_risk"
  | "prop_block_reason"
  | "prop_remaining_daily_buffer"
  | "prop_remaining_overall_buffer"
>;
type LivePropProfileConfig = {
  server: string;
  login: string;
  password: string;
  terminalPath: string | null;
  startingBalance: number;
  highImpactNewsLockout: boolean;
  profile: PropAccountState["profile"];
};

const execFileAsync = promisify(execFile);
const DEFAULT_HISTORY_LIMIT = 6;
const DEFAULT_PROP_STARTING_BALANCE = 100000;

export function getConfiguredEngineRoot() {
  const value = process.env.SYNTHETIC_ENGINE_ROOT?.trim();
  return value ? value : null;
}

function buildMockFreshCall({
  symbol,
  accountMode,
  propAccountState,
}: {
  symbol: SymbolCode;
  accountMode: AccountMode;
  propAccountState: PropAccountState | null;
}): FreshCallResponse {
  const base = latestMockCall(symbol);

  return applyAccountMode({
    base,
    accountMode,
    propAccountState,
  });
}

function applyAccountMode({
  base,
  accountMode,
  propAccountState,
}: {
  base: BaseFreshCall;
  accountMode: AccountMode;
  propAccountState: PropAccountState | null;
}): FreshCallResponse {

  if (accountMode === "own_account") {
    return freshCallResponseSchema.parse({
      ...base,
      account_mode: "own_account",
      prop_compliance: null,
      prop_adjusted_risk: null,
      prop_block_reason: null,
      prop_remaining_daily_buffer: null,
      prop_remaining_overall_buffer: null,
    });
  }

  const compliance = evaluatePropCompliance({
    call: base,
    accountState: propAccountState,
    proposedRiskPercent: 1,
  });

  return freshCallResponseSchema.parse({
    ...base,
    account_mode: "prop_firm",
    prop_compliance: compliance.status,
    prop_adjusted_risk: compliance.adjustedRiskPercent,
    prop_block_reason: compliance.blockReason,
    prop_remaining_daily_buffer: compliance.remainingDailyBuffer,
    prop_remaining_overall_buffer: compliance.remainingOverallBuffer,
  });
}

function normalizeNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
}

function normalizeText(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }

  const normalized = value.trim();
  return normalized ? normalized : null;
}

function normalizeConnectionField(value: string | null | undefined) {
  return normalizeText(value ?? null);
}

function withTelemetry(
  profile: PropAccountState,
  telemetry: PropProfileResponse["telemetry"],
): PropProfileResponse {
  return {
    ...profile,
    telemetry,
  };
}

function classifyAlertType(call: BaseFreshCall["call"], tradeStatus: string) {
  return tradeStatus === "valid" && call !== "stand_aside"
    ? "setup_candidate"
    : "context_update";
}

function buildDecisionSummary(base: BaseFreshCall): string | null {
  if (base.trade_status !== "valid" || base.call === "stand_aside") {
    return null;
  }

  return `${base.call === "buy_candidate" ? "buy" : "sell"} setup ready; ${
    base.why ?? "the market structure is aligned"
  }`;
}

function mapLiveSnapshot(raw: Record<string, unknown>, symbol: SymbolCode): BaseFreshCall {
  const call =
    raw.call === "buy_candidate" ||
    raw.call === "sell_candidate" ||
    raw.call === "stand_aside"
      ? raw.call
      : "stand_aside";
  const tradeStatus = normalizeText(raw.trade_status) ?? "not_valid";
  const why =
    normalizeText(raw.why) ??
    normalizeText(raw.briefing) ??
    normalizeText(raw.decision_summary);

  const base: BaseFreshCall = {
    symbol,
    call,
    alert_type: normalizeText(raw.alert_type) ?? classifyAlertType(call, tradeStatus),
    trade_status: tradeStatus,
    confidence: normalizeNumber(raw.confidence),
    regime: normalizeText(raw.regime),
    direction_bias: normalizeText(raw.direction_bias),
    why,
    wait_for: normalizeText(raw.wait_for),
    decision_summary: normalizeText(raw.decision_summary),
    entry_area: normalizeText(raw.entry_area),
    stop_area: normalizeText(raw.stop_area),
    target_area: normalizeText(raw.target_area),
    entry: normalizeNumber(raw.entry),
    stop_loss: normalizeNumber(raw.stop_loss),
    take_profit: normalizeNumber(raw.take_profit),
    reward_risk: normalizeNumber(raw.reward_risk),
    generated_at: new Date().toISOString(),
  };

  return {
    ...base,
    decision_summary: base.decision_summary ?? buildDecisionSummary(base),
  };
}

async function executePythonSnapshot({
  engineRoot,
  pythonCommand,
  pythonArgs,
  symbol,
}: {
  engineRoot: string;
  pythonCommand: string;
  pythonArgs: string[];
  symbol: SymbolCode;
}): Promise<BaseFreshCall> {
  const maxLiveTicks = Number(process.env.SYNTHETIC_ENGINE_MAX_LIVE_TICKS ?? "5");
  const pythonPath = `${engineRoot}\\src${
    process.env.PYTHONPATH ? `;${process.env.PYTHONPATH}` : ""
  }`;
  const pythonScript = `
import asyncio
import json
from synthetic_trader.live.market_snapshot import build_watch_alert, run_live_snapshot

snapshot = asyncio.run(
    run_live_snapshot(
        symbol="${symbol}",
        warmup_count=5000,
        timeframe_sec=60,
        higher_timeframe_sec=300,
        max_live_ticks=${Number.isFinite(maxLiveTicks) ? maxLiveTicks : 5},
    )
)
print(json.dumps(build_watch_alert(snapshot)))
`.trim();

  const { stdout } = await execFileAsync(
    pythonCommand,
    [...pythonArgs, "-c", pythonScript],
    {
      cwd: engineRoot,
      env: {
        ...process.env,
        PYTHONPATH: pythonPath,
      },
      timeout: 20000,
      windowsHide: true,
    },
  );

  const parsed = JSON.parse(stdout.trim()) as Record<string, unknown>;
  return mapLiveSnapshot(parsed, symbol);
}

export async function readLiveSnapshot({
  engineRoot,
  symbol,
}: {
  engineRoot: string;
  symbol: SymbolCode;
}): Promise<BaseFreshCall> {
  const configuredPython = process.env.SYNTHETIC_ENGINE_PYTHON?.trim();
  const candidates = configuredPython
    ? [{ command: configuredPython, args: [] as string[] }]
    : [
        { command: "python", args: [] as string[] },
        { command: "py", args: ["-3"] as string[] },
      ];

  let lastError: unknown;

  for (const candidate of candidates) {
    try {
      return await executePythonSnapshot({
        engineRoot,
        pythonCommand: candidate.command,
        pythonArgs: candidate.args,
        symbol,
      });
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError instanceof Error
    ? lastError
    : new Error("Unable to execute live snapshot");
}

export const liveSnapshotAdapter = {
  read: readLiveSnapshot,
};

async function executePythonPropProfile({
  engineRoot,
  pythonCommand,
  pythonArgs,
  config,
}: {
  engineRoot: string;
  pythonCommand: string;
  pythonArgs: string[];
  config: LivePropProfileConfig;
}): Promise<PropAccountState> {
  const pythonPath = `${engineRoot}\\src${
    process.env.PYTHONPATH ? `;${process.env.PYTHONPATH}` : ""
  }`;
  const escapedPassword = JSON.stringify(config.password);
  const escapedServer = JSON.stringify(config.server);
  const escapedTerminal = config.terminalPath
    ? JSON.stringify(config.terminalPath)
    : "None";
  const pythonScript = `
import json
from datetime import datetime
import MetaTrader5 as mt5

terminal_path = ${escapedTerminal}
if terminal_path:
    initialized = mt5.initialize(path=terminal_path)
else:
    initialized = mt5.initialize()

if not initialized:
    raise RuntimeError(f"mt5_initialize_failed:{mt5.last_error()}")

try:
    if not mt5.login(int(${config.login}), password=${escapedPassword}, server=${escapedServer}):
        raise RuntimeError(f"mt5_login_failed:{mt5.last_error()}")

    account = mt5.account_info()
    if account is None:
        raise RuntimeError("mt5_account_info_missing")

    positions = mt5.positions_get() or []
    floating_loss = 0.0
    for position in positions:
        profit = float(getattr(position, "profit", 0.0) or 0.0)
        if profit < 0:
            floating_loss += abs(profit)

    start_of_day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(start_of_day, datetime.now()) or []
    realized_loss = 0.0
    for deal in deals:
        profit = float(getattr(deal, "profit", 0.0) or 0.0)
        if profit < 0:
            realized_loss += abs(profit)

    print(json.dumps({
        "currentBalance": float(account.balance),
        "currentEquity": float(account.equity),
        "todaysRealizedLoss": round(realized_loss, 2),
        "todaysFloatingLossExposure": round(floating_loss, 2),
    }))
finally:
    mt5.shutdown()
`.trim();

  const { stdout } = await execFileAsync(
    pythonCommand,
    [...pythonArgs, "-c", pythonScript],
    {
      cwd: engineRoot,
      env: {
        ...process.env,
        PYTHONPATH: pythonPath,
      },
      timeout: 20000,
      windowsHide: true,
    },
  );

  const parsed = JSON.parse(stdout.trim()) as {
    currentBalance: number;
    currentEquity: number;
    todaysRealizedLoss: number;
    todaysFloatingLossExposure: number;
  };

  return {
    profile: config.profile,
    startingBalance: config.startingBalance,
    currentBalance: parsed.currentBalance,
    currentEquity: parsed.currentEquity,
    todaysRealizedLoss: parsed.todaysRealizedLoss,
    todaysFloatingLossExposure: parsed.todaysFloatingLossExposure,
    highImpactNewsLockout: config.highImpactNewsLockout,
  };
}

export async function readLivePropProfile({
  engineRoot,
  config,
}: {
  engineRoot: string;
  config: LivePropProfileConfig;
}): Promise<PropAccountState> {
  const configuredPython = process.env.SYNTHETIC_ENGINE_PYTHON?.trim();
  const candidates = configuredPython
    ? [{ command: configuredPython, args: [] as string[] }]
    : [
        { command: "python", args: [] as string[] },
        { command: "py", args: ["-3"] as string[] },
      ];

  let lastError: unknown;

  for (const candidate of candidates) {
    try {
      return await executePythonPropProfile({
        engineRoot,
        pythonCommand: candidate.command,
        pythonArgs: candidate.args,
        config,
      });
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError instanceof Error
    ? lastError
    : new Error("Unable to execute live prop profile");
}

export const livePropProfileAdapter = {
  read: readLivePropProfile,
};

function getHistoryJournalPath() {
  const configured = process.env.SYNTHETIC_OPERATOR_HISTORY_PATH?.trim();
  return configured
    ? configured
    : `${process.cwd()}\\.data\\operator-call-history.jsonl`;
}

function getConfiguredLivePropProfile(): LivePropProfileConfig | null {
  const server = process.env.SYNTHETIC_MT5_SERVER?.trim();
  const login = process.env.SYNTHETIC_MT5_LOGIN?.trim();
  const password = process.env.SYNTHETIC_MT5_PASSWORD?.trim();
  const terminalPath = process.env.SYNTHETIC_MT5_TERMINAL_PATH?.trim() ?? null;
  const configuredStartingBalance = Number(process.env.SYNTHETIC_PROP_STARTING_BALANCE ?? "");
  const startingBalance = Number.isFinite(configuredStartingBalance)
    ? configuredStartingBalance
    : DEFAULT_PROP_STARTING_BALANCE;

  if (!server || !login || !password) {
    return null;
  }

  return {
    server,
    login,
    password,
    terminalPath,
    startingBalance,
    highImpactNewsLockout:
      String(process.env.SYNTHETIC_PROP_NEWS_LOCKOUT ?? "").toLowerCase() === "true",
    profile: "blueberry_2step_funded",
  };
}

function resolveRequestedPropConfig(
  request: PropProfileRequest | null | undefined,
): LivePropProfileConfig | null {
  const requestedServer = normalizeConnectionField(request?.connection?.server ?? null);
  const requestedLogin = normalizeConnectionField(request?.connection?.login ?? null);
  const requestedPassword = normalizeConnectionField(request?.connection?.password ?? null);
  const requestedTerminalPath = normalizeConnectionField(
    request?.connection?.terminalPath ?? null,
  );
  const requestedStartingBalance = Number.isFinite(request?.startingBalance)
    ? Number(request?.startingBalance)
    : Number.isFinite(request?.connection?.startingBalance)
      ? Number(request?.connection?.startingBalance)
      : DEFAULT_PROP_STARTING_BALANCE;

  if (requestedServer && requestedLogin && requestedPassword) {
    return {
      server: requestedServer,
      login: requestedLogin,
      password: requestedPassword,
      terminalPath: requestedTerminalPath,
      startingBalance: requestedStartingBalance,
      highImpactNewsLockout:
        String(process.env.SYNTHETIC_PROP_NEWS_LOCKOUT ?? "").toLowerCase() === "true",
      profile: "blueberry_2step_funded",
    };
  }

  const fallback = getConfiguredLivePropProfile();
  if (!fallback) {
    return null;
  }

  return {
    ...fallback,
    startingBalance: requestedStartingBalance,
  };
}

async function appendHistoryEntry(call: FreshCallResponse) {
  const journalPath = getHistoryJournalPath();
  await mkdir(dirname(journalPath), { recursive: true });
  await appendFile(journalPath, `${JSON.stringify(call)}\n`, "utf8");
}

async function readHistoryEntries(symbol: SymbolCode, limit = DEFAULT_HISTORY_LIMIT) {
  try {
    const journalPath = getHistoryJournalPath();
    const contents = await readFile(journalPath, "utf8");
    const entries = contents
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => freshCallResponseSchema.parse(JSON.parse(line)))
      .filter((entry) => entry.symbol === symbol)
      .sort((left, right) => right.generated_at.localeCompare(left.generated_at));

    return entries.slice(0, limit);
  } catch {
    return [];
  }
}

export async function runFreshCall({
  symbol,
  accountMode,
  propAccountState,
  propConnection,
}: {
  symbol: SymbolCode;
  accountMode: AccountMode;
  propAccountState: PropAccountState | null;
  propConnection?: PropConnectionInput | null;
}): Promise<FreshCallResponse> {
  void propConnection;

  const engineRoot = getConfiguredEngineRoot();
  let result: FreshCallResponse;

  if (!engineRoot) {
    result = buildMockFreshCall({ symbol, accountMode, propAccountState });
  } else {
    try {
      const base = await liveSnapshotAdapter.read({ engineRoot, symbol });
      result = applyAccountMode({
        base,
        accountMode,
        propAccountState,
      });
    } catch {
      result = buildMockFreshCall({ symbol, accountMode, propAccountState });
    }
  }

  try {
    await appendHistoryEntry(result);
  } catch {
    // History should not break the live call path.
  }

  return result;
}

export async function getLatestCall(symbol: SymbolCode) {
  return runFreshCall({
    symbol,
    accountMode: "own_account",
    propAccountState: null,
  });
}

export async function getRecentHistory(symbol: SymbolCode) {
  const history = await readHistoryEntries(symbol);

  return {
    history: history.length > 0 ? history : recentMockHistory(symbol),
  };
}

export async function getSystemStatus() {
  const engineRoot = getConfiguredEngineRoot();

  return {
    ...mockSystemStatus,
    backend_status: engineRoot ? "live_bridge_ready" : mockSystemStatus.backend_status,
  };
}

export async function getCurrentPropProfile() {
  const engineRoot = getConfiguredEngineRoot();
  const liveConfig = getConfiguredLivePropProfile();

  if (!engineRoot || !liveConfig) {
    return mockCurrentPropProfile;
  }

  try {
    const profile = await livePropProfileAdapter.read({
      engineRoot,
      config: liveConfig,
    });

    return withTelemetry(profile, {
      status: "own_account_fallback",
      message: "Using own-account fallback",
    });
  } catch {
    return mockCurrentPropProfile;
  }
}

export async function getCurrentPropProfileForRequest(
  request: PropProfileRequest | null | undefined,
) {
  const engineRoot = getConfiguredEngineRoot();
  const liveConfig = resolveRequestedPropConfig(request);
  const usedFallback =
    !request?.connection?.server &&
    !request?.connection?.login &&
    !request?.connection?.password;

  if (!engineRoot || !liveConfig) {
    return mockCurrentPropProfile;
  }

  try {
    const profile = await livePropProfileAdapter.read({
      engineRoot,
      config: liveConfig,
    });

    return withTelemetry(
      profile,
      usedFallback
        ? {
            status: "own_account_fallback",
            message: "Using own-account fallback",
          }
        : {
            status: "live_confirmed",
            message: "Live prop check confirmed",
          },
    );
  } catch {
    return mockCurrentPropProfile;
  }
}
