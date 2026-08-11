# SynthCallExecutor — MQL5 production executor

The MQL5 side of the **Python research lab → MQL5 execution engine** split.

- **Python** (this repo) is the quantitative research laboratory: EGARCH forecast,
  band geometry, walk-forward validation, the Stage-3 empirical gate, and the
  outcomes journal. It decides *what* to trade and writes an approved call to a
  small JSON file.
- **This EA** is the thin production executor: it polls that file, places the
  order natively in MT5 with broker SL/TP, enforces the safety guards, and
  reports execution state back.

No Python→MT5 IPC exists in the execution path — no `order_send` round-trip, no
`initialize`/`login` handshake on every read, none of the "MT5 not connected"
or "retry live read" failure modes. The EA lives *inside* the terminal and
executes at native tick speed.

## Why a file handoff does not slow execution

- The EA polls the call file on a **1-second `OnTimer`** (microseconds of local
  I/O). Order placement itself happens with `CTrade` at tick speed.
- `OnTick` stays free for position management (breakeven trail, MFE tracking).
- The heavy work (EGARCH, geometry, gate) is done *ahead of time* in Python —
  the EA never computes anything on the hot path.

## The honest gate (only proven calls execute)

By default (`InpRequireProven=true`) the EA **refuses every call whose
`evidence_status` is not `proven`**. "Proven" means the (symbol, trigger_type)
has cleared the Stage-3 floor on market-verified outcomes in the journal — the
same rule the dashboard shows. `still_learning` and `suppressed` calls are
never executed. This is the production version of the proven-only execution
mode: a call type must earn its size with real market evidence before the EA
touches the account.

## File protocol (MT5 Common Files folder)

Path: `%APPDATA%\MetaQuotes\Terminal\Common\Files` (shared by every terminal
instance on the machine; the EA reads it with the `FILE_COMMON` flag).

| File | Direction | Contents |
|---|---|---|
| `synth_calls_R_75.json` | Python → EA | The approved call (single record, atomic write) |
| `synth_calls_R_100.json` | Python → EA | Same, for the other chart |
| `synth_ea_state_R_75.json` | EA → Python | Execution state (call_id, status, ticket, open price, MFE) |
| `synth_ea_state_R_100.json` | EA → Python | Same |

### Call record (written by `synthetic_trader.execution.ea_emitter`)

```json
{
  "version": 1,
  "call_id": "R_75_2026-08-11-10-30-00_buy",
  "symbol": "R_75",
  "venue_symbol": "SYN75",
  "direction": "buy",
  "entry": 1820.5,
  "stop_loss": 1818.0,
  "take_profit": 1826.0,
  "volume": 0.2,
  "magic": 7788123,
  "issued_at_epoch": 1786390000.0,
  "expiry_epoch": 1786393600.0,
  "horizon_sec": 3600,
  "evidence_status": "proven",
  "reward_risk": 4.0
}
```

The EA's `JsonGetValue` extracts the fields it needs from this flat schema.
Writes are atomic (tmp + rename) so the EA never reads a half-written file,
and idempotent per trade: re-emitting the same direction + levels does not
rewrite the file (the first `call_id` survives), so a still-alive plan is not
re-submitted to the EA on every poll — the EA dedupes by `call_id` and would
otherwise re-open the same trade after a position closes.  A genuinely new
trade (different levels) always replaces the file.

## Installing

1. Copy `SynthCallExecutor.mq5` to your terminal's experts folder:
   `C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\<TerminalID>\MQL5\Experts\`
2. Open it in **MetaEditor** and compile (`F7`). No includes beyond the
   standard library (`<Trade\Trade.mqh>`) are needed.
3. In MT5: **Tools → Options → Expert Advisors → Allow Algo Trading**.
4. Attach the EA to a **SYN75 chart** (inputs: `InpCallFile=synth_calls_R_75.json`,
   `InpStateFile=synth_ea_state_R_75.json`). Attach a second instance to the
   **SYN100 chart** with the R_100 file names.
5. Verify the magic number matches the Python side (`EA_DEFAULT_MAGIC`, default
   `7788123`), or set both to your own value.

## Emitting calls from Python

**Live path (automatic, opt-in):** set `SYNTH_EA_EMIT=1` in `.env.local`. Every
time the live snapshot pipeline produces a proven buy/sell candidate,
`build_watch_alert` writes it to the Common Files folder. Volume comes from
`SYNTH_EA_VOLUME` (default 0.2) scaled by the Stage-3 `size_multiplier`.

**CLI (manual / scheduled):**

```bash
python -m synthetic_trader.cli emit-ea-call --symbol R_75
```

Options: `--volume`, `--files-dir`, `--allow-unproven` (paper/harness only).

**Read the EA's state back** (Python):

```python
from synthetic_trader.execution.ea_emitter import read_ea_state
state = read_ea_state("R_75")   # {"call_id": ..., "status": "executed", ...}
```

## Safety guards (inputs)

| Input | Default | Purpose |
|---|---|---|
| `InpRequireProven` | `true` | Only execute `evidence_status=proven` |
| `InpMagic` | `7788123` | Separates EA trades from manual ones |
| `InpMaxSpreadPoints` | `80` | Skip entry when spread is too wide |
| `InpMaxSlippagePoints` | `50` | Max deviation for market orders |
| `InpMaxDailyLossPct` | `5.0` | Halt new entries after this daily drawdown |
| `InpBreakevenTrail` | `true` | Move SL to entry at `InpBreakevenFrac` of target |
| `InpVolume` | `0.0` | Fixed volume (0 = use the call's volume) |

One position at a time per symbol (the band strategy is single-position); a
new call while a position is open is retried on the next poll, not dropped.

## Testing in the Strategy Tester

The EA is designed to be tested in the MT5 Strategy Tester:

1. Drop a call file (e.g. `synth_calls_R_75.json`) into the **tester's Files
   folder** — in the tester, `FILE_COMMON` reads from the terminal's Common
   folder, so the file lands where the EA looks.
2. Run the tester on **SYN75, "Every tick"** mode (the only honest mode — the
   MQL5 docs warn that "Open prices only" can fabricate a grail curve).
3. The EA will place the order at the recorded levels, respect expiry/SL/TP,
   and write `synth_ea_state_R_75.json`.

Caveats from the MQL5 docs to keep in mind: `Comment/Print` are suppressed
during optimization passes, file I/O is restricted in the MQL5 Cloud Network,
and `OnTimer` works in the tester. Backtest *signal quality* stays in Python
against the tick corpus — the tester here validates execution mechanics, not
edge.

## Continuous verification (scheduled, after each commit)

The one-command loop (`bash mql5/verify_all.sh`, see `verify_all.ps1`) is wired
into Task Scheduler so the MQL5 build verifies itself continuously:

- **`setup-mql5-verify-task.ps1`** registers an hourly `MQL5Verify` task and
  installs a git `post-commit` hook, so every commit fires the loop instantly
  and hourly ticks catch commits made by GUI tools / rebases.
- **`run-mql5-verify-task.ps1`** is the Task Scheduler action. It is git-gated:
  a `PASS` for the current HEAD is skipped in seconds; a `FAIL` is retried on
  the next tick. It logs to `.data/mql5_verify_task.log` and persists the last
  result table to `.data/mql5_verify_state.json`.
- **Email**: set `MQL5_VERIFY_SMTP_SERVER/TO/FROM/USER/PASS` (or edit the
  inline defaults in the wrapper) and each real run emails the PASS/FAIL
  table; unconfigured = disabled.

Uninstall with `setup-mql5-verify-task.ps1 -Unregister`. One gotcha baked into
both scripts: the hook invokes schtasks through PowerShell (`-Command
'schtasks /Run /TN ...'`) because Git-Bash's sh path-converts a bare `/Run`
into `R:\un`, and hook files are written without a UTF-8 BOM so the `#!/bin/sh`
shebang survives.

### ⚠️ Stale input-set hazard (read before debugging a "rebuilt" suite)

The MT5 Strategy Tester **auto-saves the parameters it just ran with** to
`MQL5\Profiles\Tester\<expert>.set` at the end of every run. On the next run
the tester silently loads that saved set OVER the freshly compiled defaults —
so a rebuilt `.ex5` can execute with **old inputs** and pass/fail for the
wrong reasons. This has bitten twice in real measurements:

- a stale `BandBackTests.set` pinned `InpVolGateRatio=1.30` while the source
  said 1.10 → every rebuilt binary reported **1 trade** in 6 months;
- the same `.set` later pinned `InpMinTargetRR=2.0` against an RR-1.2
  geometry → **`entries=0`** despite 2,271 signals passing every gate, and
  then pinned a sweep cell's values against a new default → stale verdicts
  that matched the previous run exactly.

`verify_all.ps1` defends against this in three layers: it purges the suite's
`.set` **before** each run (so a rebuilt `.ex5` always runs its own
compiled defaults), **after** each run (the tester re-saves at shutdown, so a
post-run purge keeps the next invocation clean), and the `-Inputs
"k=v;k=v"` override deliberately writes its own `.set` and points
`ExpertParameters=` at it for sweep runs. Symptom to look for: the verifier
log stops printing "purged stale input set". If a rebuilt suite behaves like
it's running old inputs, check `MQL5\Profiles\Tester\<expert>.set` (mtime +
contents) — and note the historical trap: PowerShell parses
`@($name + ".set", $name.Replace(...))` as ONE space-joined string, so a
purge loop must parenthesize each array element or it silently never runs.

### Depth-split regression gate (BandBackTests)

The band's per-cap edge-depth table (`depth <= 1.25/1.50/2.00/2.50/3.00:
n / hit / exp`) is a measurement contract: `verify_all.ps1` parses it from
the CURRENT run's log block (everything after the last suite start marker —
otherwise cells from earlier runs get mixed in and the cumulative-n check
fails spuriously, as it did on the first integration run) and folds the
verdict into the suite's PASS/FAIL:

- **Presence** — if the report disappears from a rebuilt suite, the suite
  FAILs with `DEPTH-REGRESSION: depth-split report MISSING`.
- **Cumulative-n monotonicity** — `n` must be non-decreasing as the cap
grows (the cells are subsets of one run); a violation fails the suite.
- **Value bands** — the `<=1.25` and `<=2.00` cells' hit must stay in
  [15%, 60%] and exp in [−0.35, +0.35]R (measured spans across geometries:
  hit 28–47% / exp −0.19 to +0.12; the bands catch the 2%-hit
  trail-disaster class while surviving window changes).

On a healthy run the summary rides in the Detail column (`depth-split: 5
cells, <=1.25 hit 28.1%/exp 0.124R, <=2.00 hit 27.7%/exp 0.106R ...`); on
violation the suite shows `FAIL ... | DEPTH-REGRESSION: <why>` and the
overall loop exits 1. Verified: healthy run PASSes with the summary,
missing-report / collapsed-hit / partial-table fixtures all FAIL with the
specific cause.

## Field notes (forward-demo pass, 2026-08-10)

Operational knowledge from attaching the EA live on SYN75 and exercising the
file handoff end-to-end (the pass itself is blocked by the account — see below).

### Attaching without the GUI: the `[StartUp]` config

MT5's Navigator/menus are custom-drawn and invisible to Windows UI Automation,
so there is no scriptable drag-drop. The deterministic attach path is the
terminal startup config (`terminal64.exe /config:<ini>`) with:

```ini
[Experts]
AllowLiveTrading=1

[StartUp]
Expert=SynthCallExecutor
Symbol=SYN75
Period=H1
```

A working config lives at `<TerminalID>\config\ea_start.ini` (a UTF-16 copy of
the live `terminal.ini` plus those sections — strip any stale `[Tester]`
section from the copy or the terminal tries to auto-run a tester at startup).
Launch the terminal with it via PowerShell `Start-Process -ArgumentList
('/config:"<path>"')` (clean quoting, no stray dialogs).

### Bugs the live pass caught (all fixed)

1. **Compile errors** — `ExecuteCall` was declared `bool` but had three bare
   `return;` statements (error 121). The EA had never been compiled against
   this terminal's compiler.
2. **Multi-line JSON truncated** — `FileReadString` in TEXT mode stops at the
   first newline, and the Python emitter writes pretty-printed JSON, so the EA
   read only `{` and silently dropped every call. `ReadCommonFile` now reads
   `FILE_BIN` + `FileReadArray` + `CharArrayToString`.
3. **Rejected call never retried after restart** — `OnInit` recovered
   `g_lastCallId` from the state file regardless of status, so a call whose
   order was rejected was treated as already-processed after every restart.
   Recovery now only remembers `status == "executed" | "closed"`.
4. **Per-second retry flood** — a server-side AT block (retcode 10026/10027)
   won't clear within a second; the EA now backs off 60s between attempts so a
   48h pass can't write ~86k rejected orders to the journal. The call is not
   marked processed, so it still fills the moment the block lifts.

### The current hard blocker: the account, not the code

Demo account `5098680` on `BlueberryMarketsSVG-Live` returns
**retcode 10026 `AutoTrading disabled by server`** for *every* order attempt —
including a manual `order_send` from Python with no EA involved. This is a
server-side account setting the broker controls; the terminal's own algo button
and `MQL_TRADE_ALLOWED` are both ON and cannot override it. The EA is attached
and retrying every 60s, and the call file (48h expiry) is in place — the moment
algo trading is enabled for the account (broker client area / support, or log
in with an account that allows it), the pending call fills automatically with
no further setup.

## Regime cross-validation (Phase-2 gate, real R_75 corpus)

`phase2_real_corpus_check.py` feeds real R_75 M5 closes (2338 bars, ~8.1 days)
through both the MQL5 RegimeEngine mirror and the Python
`RegimeShiftDetector` (HMM + CUSUM) and compares them on a mapped volatility
axis. The engines measure DIFFERENT axes and that is the reconciliation:

| Axis | MQL5 RegimeEngine | Python HMM/CUSUM |
|---|---|---|
| Structure | TREND/RANGE/COMPRESSION/EXPANSION/TRANSITION (200-bar window) | none |
| Vol level | ATR percentile + ratio (relative to a 100-bar window) | LOW/NORMAL/HIGH (slow EMA-adapted, quasi-absolute) |
| Breaks | TRANSITION (vol-of-vol + efficiency change) | CUSUM structural-break alerts |

**Measured agreement on the mapped vol bucket: 68%** (264/388 windows). The
remaining 32% classifies into three documented axis differences, none a bug:

1. **RANGE → Python LOW (81 windows)** — quiet, choppy markets. Both are
   right: the MQL5 structure label is RANGE, the Python absolute-vol label is
   LOW. Consumers must read the regime label AND the ATR context together;
   the MQL5 vol measures are window-relative by design.
2. **EXPANSION → Python NORMAL on genuine spikes (ratio 1.5–4×)** — the
   Python HMM adapts too slowly (EMA 0.02) to register real vol explosions;
   the MQL5 detector is the MORE responsive one here. Trust MQL5 on genuine
   expansions.
3. **TRANSITION over-fires vs CUSUM (57 vs 8 alerts; 23% aligned)** — the
   vol-of-vol detector oscillates on a mean-reverting instrument. Reconciled
   by raising `REGIME_TRANSITION_THRESHOLD` 0.55 → 0.70 and treating
   TRANSITION as advisory (its confidence is already disagreement-penalized).

Engine changes applied in this gate (mirror + `Regime/RegimeEngine.mqh`, both
kept in lockstep; Phase-2 tester suite still green):
- `REGIME_TRANSITION_THRESHOLD` 0.55 → 0.70.
- `s_expand` now requires a real ATR ratio lift (>1.15) — a high relative
  percentile alone no longer fires EXPANSION.

Phase 3 consumers should treat the regime label as the structure axis and
`atr_ratio`/`atr_percentile` as the volatility axis, never a single number.

## Phase 3 — Structure (SMC primitives), 2026-08-11

`Structure/` implements the objective structure layer consumed by the research
strategies (never the active band leg by default):

- **`SwingDetector`** — fractal swings (strictly greater high / lesser low over
  `left`+`right` closed bars; a swing only becomes usable after its right guard
  confirms it, so there is no repainting). `strength` is the swing's prominence
  in ATR multiples, clamped 0..1 — symbol/broker independent.
- **`BOSDetector`** — break of structure: a close through the last confirmed
  swing high (bullish) / low (bearish), one event per level crossing.
- **`CHOCHDetector`** — change of character: uptrend (HH+HL) broken by a close
  below the last higher low, or downtrend (LH+LL) broken by a close above the
  last lower high. The trend definition is recomputed per bar from the last two
  confirmed swings of each polarity — stateless, cannot drift.
- **`LiquidityEngine`** — swing highs/lows as resting liquidity; a sweep is a
  wick that exceeds the level by ≥ `min_exceed_atr`×ATR then closes back
  inside. Sweeps above a high are bearish intent (−1), below a low bullish (+1).
- **`SupportResistance`** — clusters raw extremes within `tol_atr`×ATR into
  levels with touch counts; a level survives only with ≥ `min_touches` touches;
  `kind` merges polarity (+1 resistance / −1 support / 0 both).
- **`DisplacementDetector`** — normalized impulse bars: body ≥ `body_mult`×ATR
  AND range ≥ `range_mult`×ATR AND the close is committed to the direction
  (close-location ≥ 0.7 up / ≤ 0.3 down).
- **`StructureEngine`** — pulls the latest closed-bar window from the Phase-2
  `CandleEngine` and aggregates: bias (bullish/bearish/neutral from the most
  recent CHOCH or BOS, swing sequence as fallback) plus the most recent event
  with direction/price/time. Event precedence on ties: CHOCH > BOS > SWEEP >
  DISPLACEMENT.

**Verification (2026-08-11):** MetaEditor compile 0 errors / 0 warnings;
Python mirror `phase3_logic_check.py` 70/70; Strategy Tester run on SYN75 —
**70 passed, 0 failed**, with Phase 1 (61) and Phase 2 (40) re-verified green
in the same `verify_all.sh` loop. One lockstep bug was caught during the build
(mirror event codes for CHOCH/DISPLACEMENT disagreed with `ENUM_STRUCTURE_EVENT`)
and fixed before the MQL5 suite shipped. The full pass is in
`Tester/logs/20260811.log` under `[PHASE3]`.

### Phase-3 real-corpus cross-validation (vs Python SMC, 2026-08-11)

`phase3_real_corpus_check.py` runs the MQL5 StructureEngine mirror and the real
Python SMC (`src/synthetic_trader/features/market_structure.py`) over every
100-bar M5 window of the real R_75 corpus (2338 bars ≈ 8.1 days), and compares
them on mapped structure axes — the same gate pattern as the Phase-2 regime
check.  It also prints an **event census** (deduped swing/BOS/CHOCH/sweep/
displacement counts with a per-day breakdown) and **bias coverage** (share of
windows with a committed direction, mean regime length, flip rate).  On the
current corpus the mirror commits to a bias in **94.6% of windows** (53.8%
bullish / 40.8% bearish), regimes persist a mean ~1.4h (longest 4.6h), and the
census runs ~25-40 swings, ~15-35 BOS, ~2-7 CHOCH, and ~6-16 sweeps per day.

**Headline agreement after reconciliation:**

| Axis | Before | After | What it measures |
|---|---|---|---|
| Bias vs `structure_bias` | 71.7% | **74.8%** | MQL5 Bias() vs Python HH+HL/LH+LL sign |
| Bias vs `structural_direction` | 78.3% | **83.9%** | MQL5 Bias() vs the decision engine's LONG/SHORT/FLAT |
| BOS — sweep footing, event view (B2a) | 70.8% | **85.9%** | last BOS event ≤8 bars **against the live level** vs Python `bos_up/down` |
| BOS — identical question (B2b) | — | **100.0%** | last-bar close vs most-recent swing level (isolates swing detection) |
| Sweep (recency-aligned) | 43.3% | **85.9%** | last sweep vs Python `liquidity_sweep_*` flags |
| Displacement | 98.7% | 98.7% | window displacement vs `displacement_atr ≥ 2` |

**The reconciliation — one real engine defect found and fixed.** The sweep
axis was 13.4% raw because the LiquidityEngine scanned *every historical swing
level* in the window, so it reported a sweep in **448/448 windows** (a feature
that never says "no" carries no information), while Python sweeps only the
most recent level (`recent_high`/`recent_low`). Fix: `DetectSweeps` now sweeps
only the most recent swing of each polarity. The over-fire collapsed to
113/448 windows and aligned agreement jumped 43.3% → 85.9%. This also lifted
the bias axes (a stale sweep was polluting the engine's last-event selection,
forcing bias onto the swing fallback when a real BOS was more recent). Two new
unit tests lock the behavior (stale-level sweep ignored / newest-level sweep
fires). Mirror updated in lockstep; suite now 70 checks.

**Documented residual disagreements (not bugs — different semantics):**

1. **Bias flips (69/448 windows).** 64 are driven by the MQL5 event override —
   a BOS/CHOCH mid-window sets MQL5 bias even when the final swing sequence
   reads HH+HL the other way (Python's `structure_bias` has no event
   override). 19 are driven by Python's momentum fallback — Python invents
   direction from ~20-bar price momentum when swings are inconclusive; MQL5
   honestly returns NEUTRAL (53 vs Python's 9 neutral windows). Both engines
   are right on their own contract: MQL5 is more event-reactive, Python more
   smoothed. Phase-4 consumers should read MQL5 bias as "most recent structure
   event direction" and Python's as "swing-sequence / momentum state".
2. **BOS residual — measured on the same footing as sweeps, then eliminated.**
   B2a (the last MQL5 BOS event inside the last 8 bars whose broken level is
   still the live most-recent swing level — the sweep-style event view) agrees
   85.9%, and B2b (the question-identical view: last-bar close vs most-recent
   swing level, isolating swing detection) agrees **100.0%** — a perfectly
   diagonal contingency (80 down / 260 none / 108 up), zero residual. The
   attribution proved the residual was 25/25 **window-edge recency**: the
   MQL5 recent swing sat at the newest confirmable bar (its right guard is the
   current bar), which Python's `candles[:-1]` convention excludes by design;
   strict-vs-flat-top swing counting was NOT the cause (it flips a BOS answer
   zero times). **Fix applied in mirror + `SwingDetector.mqh`:** swings are
   now confirmed only by bars strictly before the current one
   (`i + right < count - 1`), the Python convention. Result: B2b 94.4% →
   **100.0%**, recent-level agreement 74.1% → **99.1%** (the strict/non-strict
   level differences were mostly edge-driven too), bias axes up (74.3 → 74.8%,
   83.5 → 83.9%), B2a up (85.0 → 85.9%). All 70 unit tests stay green and the
   live tester suite (below) improved 82.9 → 83.2%.
3. **Swing counts** differ in 136/448 windows (strict vs non-strict fractals;
   mean +0.12 swings/window) — material only when flat tops matter, and (per
   the B2b attribution) rarely enough to flip a BOS answer.

Per the architecture stance, structure stays a **research input** regardless
of this agreement — it feeds the research strategies, never the active band
leg.

### Live-tester gate — the real .mqh vs Python, on the SYN75 chart (2026-08-11)

The cross-checks above compared the Python MIRROR of the engine against
Python — they proved the math, not the compiled `.mqh`.  **`Tests/
StructureLiveTests.mq5`** closes that gap: it streams the tester's own SYN75
M5 bars (up to 50k, oldest-first) through the real `CStructureEngine` and
through `PythonParity/StructureParity.mqh` — a faithful MQL5 port of Python's
`market_structure_features` + `structural_direction` — and compares them per
closed bar inside the MT5 Strategy Tester.

The parity port is itself gated by **`mql5/structure_parity_check.py`**, which
mirrors the port line-for-line and asserts it equals the real Python functions
on crafted edge series, 150 seeded-random windows, and 120 real-corpus
windows (**279/279**).  Without that, a port bug would silently corrupt the
tester comparison.

**Result (2026-08-11, SYN75, tester cache ~Feb→Aug 2026; re-measured after the
window-edge alignment):**

```
[STRUCTLIVE] loaded 50000 M5 bars on SYN75 (window 100, swing 2/2)
[STRUCTLIVE] compared 49901 bars, agreement 83.2% (engine-neutral 3729, python-flat 161)
[STRUCTLIVE] === 41524 passed, 8377 failed ===  (83.2% agreement on SYN75 M5)
[STRUCTLIVE] SUITE PASSED
```

83.2% on ~50k bars across six months of real market data matches the
Python-side measurement (83.9% on the 8-day corpus) — the compiled engine
reproduces Python's `structural_direction` at the same rate the mirror did.
The residual is the documented semantic: the engine returns NEUTRAL 3729
windows where Python invents a direction via its momentum fallback (161 flat),
plus the event-driven vs smoothed bias conventions.  The suite is
auto-discovered by `verify_all.ps1` (filter widened to `*Tests.mq5`) and runs
alongside Phases 1–4.

**Phase-5 decision gate wired into the live path (same run, 2026-08-11):**
`CConfidenceEngine.Gate` now scores every structure bar live — setup quality
from the window's structure-event density, formal setup = a BOS/CHOCH
agreeing with the bias, composite via `CScoringEngine` (regime/structure axes
neutral on this path, risk 0.5, execution 1.0) — and logs the
strong/weak/wait verdict per bar against Python's `structural_direction`:

```
[STRUCTLIVE] gate verdicts: strong_buy=20147 weak_buy=3388 wait=3729 weak_sell=3317 strong_sell=19320
[STRUCTLIVE] gate vs python: directional=46172 agree=41436 disagree=4663 python-flat=73 wait=3729  agreement 89.9%
[STRUCTLIVE] === 41524 passed, 8377 failed ===  (bias 83.2% + gate 89.9% on SYN75 M5)
[STRUCTLIVE] SUITE PASSED — reconciled engine + decision gate agree with Python structural_direction live on SYN75
```

The compiled gate's directional verdicts agree with Python on **89.9%** of
committed bars (41,436/46,099) — above the raw bias agreement (83.2%): the
gate's confidence filter routes the weakest setups into WEAK (6,705) and
stands aside on all 3,729 neutral-bias bars (its 3,729 WAITs are exactly the
engine-neutral windows — no committed direction fell below min-confidence,
same uniformly-high-confidence finding as the band leg).  Verdict per bar is
logged (first 12 gate disagreements include the composite and setup flags),
and the suite now has two PASS thresholds (bias ≥ 70%, gate ≥ 65%).

## Phase 4 — Strategies, 2026-08-11

`Strategies/` holds the strategy layer. One leg is ACTIVE, five are research
skeletons, and the registry enforces regime awareness:

- **`BandGeometry` (★ ACTIVE)** — the exact port of Python `band_geometry.py`
  (`ComputeLevels` reproduces `band_levels`; `HorizonSigma` = σ_per_bar·√bars)
  plus the `vol_band.py` entry gates (`VolExtended` 1.3×σ-EMA gate,
  `EntryDirection` z-extension fade at |z| ≥ 1.0, `Confidence`
  0.55+0.35·|z|/(3·z_entry) capped 0.95) and the breakeven trail
  (`UpdateMFE`/`TrailArmed`/`EffectiveStop` — stop moves to entry once MFE ≥
  0.3 × planned RR, converting would-be -1R losses into ~0R exits).  The
  EGARCH forecaster stays in Python; this module receives σ_per_bar / prev_
  sigma / the price EMA as inputs and reproduces the exact level math.
- **Research skeletons** — TrendContinuation, Breakout, MeanReversion,
  LiquiditySweep, Pullback. Each carries the full H1–H10 hypothesis block in
  its header (hypothesis / why it might work / measurable variables /
  expected regime / invalidation / expected RR / data required / how it
  could fail / OOS test / overfit detection) and returns WAIT until it passes
  the same walk-forward gates as the band leg.
- **`StrategyEngine`** — the regime-allowance matrix (`MatrixAllows`: TREND →
  trend/breakout/pullback; RANGE → mean-reversion/liquidity-sweep;
  COMPRESSION → breakout/liquidity-sweep; EXPANSION → band only), the
  research hard-disable (`IsAllowed` — only the validated band leg is live
  today), `AllowedStrategies`, and `Evaluate` dispatch producing
  `StrategyCandidate{strategy, decision, entry, stop, target, setup_quality,
  confidence, reason_codes, required_regime}` (struct in `Core/Constants.mqh`).

**Verification (2026-08-11):** MetaEditor compile 0 errors / 0 warnings;
Python mirror `phase4_logic_check.py` 62/62 — itself checked against the REAL
Python `band_geometry.band_levels` to 1e-12 on the shared cases, so the MQL5
port reproduces Python `band_levels` within tolerance transitively (the Phase-4
gate).  Strategy Tester run on SYN75 — **65 passed, 0 failed**, Phases 1–3
(61/40/70) re-verified green in the same `verify_all.sh` loop.  One test bug
was caught and fixed (allowed-list assertions used the runtime disabled-state
function instead of the end-state matrix); the runtime band-only behavior is
now locked by a test.

### First Strategy Tester backtest of the band leg (SYN75 M5, 2026-08-11)

`Tests/BandBackTests.mq5` streams the tester's SYN75 M5 history (50,000 bars,
100% history quality, back to 2024-11-27) through the full band path: the
**bit-faithful port of the online-SGD EGARCH(1,1) forecaster** (the exact
estimator `backtest-vol` uses — verified to 1e-12 against the real Python
forecaster on the R_75 corpus: `_probe_egarch_parity.py`; two port bugs were
found and fixed along the way: Python never applies beta's SGD update — beta is
only the persistence soft-cap — and warmup `garch_sigma` is
`sqrt(long_run_var)`, not 0), the vol-extension gate, z-entry fade, and the
PaperBroker execution incl. the breakeven trail (entry at signal close,
stop-first intrabar checks, 1h expiry, single position).

**Result (2026-08-11, tester window Aug 10→11, full 50k-bar history streamed):**

```
loaded 50000 M5 bars on SYN75          (history 2024-11-27 → 2026-08-11)
trades=3831  wins=168  losses=3663  hit=4.4%  (long 1838, short 1993)
expectancy: -0.347 R/trade gross | -0.397 R @0.05 cost | -0.447 R @0.10 cost
avg win +3.311R  avg loss -0.514R  profit factor 0.30
max drawdown 1332.80R (peak 5.00R)  |  long -0.339R  short -0.353R
```

**Honest read:** the port runs end-to-end on real tester data and the mechanics
work (168 target hits at +3.31R avg), but the leg is **not tradeable on the
6-month window** — expectancy −0.347R gross. The root cause is the gate
estimator, not the port: the online-SGD EGARCH is degenerate on this data (its
σ spikes to ~1,218%/bar during SGD blowups, passing the vol gate ~11% of bars
vs ~1.7% for a stable EWMA), so the leg over-trades into adverse windows. This
matches the Python side's own behavior on the same estimator. The positive
Python cells measured earlier (+0.65–0.90R) came from narrower windows or the
calibrated fixed-parameter EGARCH — the next backtest step is to run this suite
against the **calibrated** R_75 EGARCH parameters (ω=-1.115, α=0.077, γ=0.011,
β=0.918) instead of the online-SGD state, which the gate already supports as
inputs. Tester model note: the INI uses `Model=1` (1-minute OHLC, standard for
a close-based strategy); switching to `Model=4` (every tick on real ticks)
needs the terminal's SYN75 tick cache and changes only intrabar fill precision.

**Decision layer added (same run, 2026-08-11):** every signal is now scored and
gated at entry by the Phase-5 layer — `ScoringEngine` composite + `ConfidenceEngine`
verdict stored on each trade — and the report splits expectancy by confidence
bucket.  **The buckets are now discriminating (2026-08-11):** a seeded
per-signal geometry sweep (`MathSrand(InpGeomSeed)`, z_entry 0.7–1.6, stop
0.15–0.35σ_h, target 0.50–1.20σ_h) varies RR and setup quality per trade, and
setup quality is **edge depth** (`|z|/z_entry`) instead of the band's own
`Confidence()` — which floors at ~0.88 for every gated signal (the z gate
guarantees `|z| ≥ z_entry`), the structural reason all 3,831 trades originally
landed STRONG.  Marginal fades score ~0.2, deep extensions ~1.0, so the
blended confidence spans the STRONG/WEAK/WAIT thresholds:

```
trades=3303  wins=167  losses=3136  hit=5.1%  (long 1582, short 1721)
expectancy: -0.330 R/trade gross | -0.380 R @0.05 cost | -0.430 R @0.10 cost

confidence buckets (per-signal geometry sweep — strong >= 0.52 w/ setup, weak >= 0.48):
  STRONG: n=2795  hit=4.6%  exp=-0.343R  (avgRR=3.74 avg z_entry=1.11 avg depth=2.62)
  WEAK:   n=311   hit=8.0%  exp=-0.236R  (avgRR=3.81 avg z_entry=1.17 avg depth=1.18)
  WAIT:   n=197   (signals the decision gate would have blocked)
  composite: min 0.710  max 0.950  mean 0.840  |  blended confidence mean 0.738
  BUCKET VERDICT: STRONG -0.343R vs WEAK -0.236R (-0.108R lift) — WEAK bucket
                  outperforms; STRONG hit 4.6% vs WEAK hit 8.0%
```

**The honest answer to "do higher-confidence trades outperform?" is NO on
this leg.**  The buckets are genuinely discriminating now — three populated
buckets, and WEAK trades are measurably the shallow fades (avg depth 1.18 vs
2.62, avg z_entry 1.17 vs 1.11) — but the higher-confidence bucket loses MORE:
STRONG −0.343R at 4.6% hit vs WEAK −0.236R at 8.0%.  Deep z-extension fades
do not mean-revert more reliably than shallow ones on this synthetic index
(the opposite, if anything).  That is a real diagnostic for the band leg: the
confidence axis the sweep built is not predictive of outcomes, and both
buckets are still negative — the leg remains untradeable, and the z-depth
fade edge needs re-testing rather than trusting the confidence spread.

**Stage-3 empirical floor gate added (same run, 2026-08-11):** every entry is
now annotated with the walk-forward empirical gate state — the
`TradeQualityEngine` journal (fed per bar: `StartPosition` → `UpdatePosition` →
`ClosePosition` with the true exit reason) holds only outcomes resolved strictly
before the current bar, so its stats are exactly what the live Stage-3 gate sees
at emission (no lookahead). The floor is the per-geometry break-even rate
`1/(1+avg planned RR) + margin` (`BreakEvenFloor` — the exact
`stage3_gate.break_even_floor` math); below `min_samples=10` the signal is
`still_learning` (paper warm-up), at/above the floor it is `proven`, below it is
`suppressed` (stand aside). The report splits kept vs suppressed, exactly like
the Python `backtest-gate` verdict:

```
Stage-3 empirical floor gate (TradeQualityEngine.BreakEvenFloor):
  floor = 1/(1+avg planned RR) + margin;  margin=0.05  min_samples=10
  mean floor at entry 25.0%  (band 4.0-RR geometry needs 25.0% to break even)
  KEPT (would trade):       n=10  hit=20.0%  exp=+0.400R  [proven 0, still_learning 10]
  SUPPRESSED (stand aside): n=3821 hit=4.3%  exp=-0.349R
  VERDICT: achieved hit 4.4% does NOT beat the 25.0% floor — the band's 4.0-RR
           geometry is NOT floor-beatable on this window — the gate stands aside
```

Trade count/expectancy unchanged (168/3663, −0.347R — entry logic untouched).
The gate behaves exactly as designed: the first 10 warm-up trades are the only
ones that would have been taken, and from trade 11 onward the 4.3% achieved hit
rate never approaches the 25% break-even floor for the 4.0-RR geometry, so the
gate suppresses everything. This is the same conclusion as the Python
`backtest-gate` on R_75: the geometry itself is not yet floor-beatable, and the
empirical gate correctly stands aside until a re-tuned geometry proves it can
clear its own break-even. (Journal note: `MAX_OUTCOME_RECORDS` caps at 2000, so
the cumulative stats freeze at the first 2,000 outcomes — representative here
since hit rate stays ~4.5% throughout.)

**Calibrated fixed-EGARCH re-run (2026-08-11):** the suite now defaults to the
**calibrated** R_75 EGARCH parameters (ω=-1.115, α=0.077, γ=0.011, β=0.918) as
fixed inputs instead of the degenerate online-SGD state (`InpGarchOmega/…/Beta`
inputs, mode default = calibrated-fixed, the same recursion as the production
estimator). Two gate changes were required to get a measurable sample on the
calibrated σ:

- **Vol gate re-based 1.3 → 1.10** — the smooth calibrated σ crosses 1.3× on
  only ~0.8% of bars (1 bar in 50k; ratio_max 1.35), collapsing the run to 1
  trade. At 1.10 the gate crosses 5.8% of bars (2,899 in the 6-month window).
- **Drift gate fixed to measure DIRECTION, not volatility** — the ADWIN-lite
  detector ran on `|log r|`, i.e. it fired on volatility bursts — the *same*
  bars the vol-extension gate opens on — so the two gates vetoed each other
  (measured: 2,899 vol crossings, 1 drift-clear, 1 entry). It now uses signed
  log returns (a persistent one-sided move), and is a switchable input
  (`InpDriftGate`, OFF by default — a vol burst IS the band's entry signal).

**A real harness bug caught in the process:** the tester silently loads the
saved input set `MQL5\Profiles\Tester\<expert>.set` over the freshly compiled
defaults — a stale `BandBackTests.set` was pinning `InpVolGateRatio=1.30`
(and the old drift gate) no matter what the source said, which is why the
earlier calibrated runs all reported 1 trade. `verify_all.ps1` now purges the
stale `.set` for each suite before every tester run, so a rebuilt .ex5 always
runs its own compiled defaults.

With the stale `.set` gone and the re-based gates, the 6-month window measures
cleanly (50k M5 bars, decision-layer split):

```
trades=2059  wins=30  losses=2029  hit=1.5%  (long 604, short 1455)
expectancy: -0.396 R/trade gross | -0.446 R @0.05 cost | -0.496 R @0.10 cost

confidence buckets (per-signal geometry sweep):
  STRONG: n=1949  hit=1.5%  exp=-0.393R  (avgRR=3.79 avg z_entry=1.13 avg depth=3.76)
  WEAK:   n=75    hit=0.0%  exp=-0.440R  (avgRR=4.00 avg z_entry=1.29 avg depth=1.18)
  WAIT:   n=35    (signals the decision gate would have blocked)
  composite: min 0.711  max 0.950  mean 0.893  |  blended confidence mean 0.853
  BUCKET VERDICT: STRONG -0.393R vs WEAK -0.440R (+0.047R lift) — STRONG bucket
                  outperforms; STRONG hit 1.5% vs WEAK hit 0.0%
```

**Honest read:** the calibrated estimator works end-to-end (2,059 trades, the
journal + floor gate + buckets all populated), but the band's 4.0-RR fade
geometry is *worse* on the calibrated σ — 1.5% hit vs the 25.8% break-even
floor, so the empirical gate correctly stands aside (KEPT only the 10 warm-up
trades, SUPPRESSED 2,049). The calibrated σ is much smoother than the
degenerate SGD state, so real vol-extension bars are rarer and mean-reversion
is weaker than the (unrealistic) SGD-driven over-trading implied. This isthe same conclusion as the Python `backtest-gate` — and now confirmed on the
production estimator inside the tester.

**Target re-derived from the journal's MFE distribution (§50, same 6-month
window):** the exit-quality journal said winners barely travel — band median
MFE **1.18R** vs the 4.00R target (the target sat ~3.4× the median travel).
Replaying the captured R_75 band paths under alternative target multipliers
(stop fixed at 1R, exact `_maybe_close` semantics) showed two things:

1. **The breakeven trail is the binding constraint, not the target.** At
   trail_frac 0.3 the trail arms at `0.3 × planned_RR` — 1.2R at RR 4.0, but
   only 0.36R at the derived RR — so at ANY target the trail races the
   target: a favorable excursion arms the trail, the stop moves to entry,
   and the same-candle dip back through entry exits at 0R (stop-first), so
   hit stays ~2-5% no matter the target (measured: 1.8% with trail vs 51.8%
   without at k=1.2R).
2. **Without the trail, the MFE zone clears its floor.** target 1.2R (=
   median MFE): hit 51.8% vs the 50.5% floor, +0.125R on the R_75 corpus;
   target 1.0R: 55.4% vs 55.0%, +0.097R.  Every RR ≥ 1.5 cell is negative
   (hit collapses past the MFE cliff).

So the band now runs the MFE-derived geometry — `InpTargetSigmaMult` 0.24σ
(= 1.2 × stop, RR 1.2), `InpMinTargetRR` 1.2, `InpTrailFrac` 0.0, and the
geometry sweep couples `target = 1.2 × stop` so every trade keeps the
reachable target — and the 6-month floor gate re-runs:

```
trades=1818  wins=712  losses=1106  hit=39.2%  (long 527, short 1291)
expectancy: -0.138 R/trade gross | -0.188 R @0.05 cost | -0.238 R @0.10 cost
avg win +1.200R  avg loss -1.000R  profit factor 0.77

confidence buckets:
  STRONG: n=1680  hit=38.8%  exp=-0.148R  (avgRR=1.20 avg z_entry=1.13 avg depth=3.88)
  WEAK:   n=64    hit=45.3%  exp=-0.003R  (avgRR=1.20 avg z_entry=1.26 avg depth=1.32)
  WAIT:   n=74

Stage-3 floor gate: mean floor at entry 50.5% (band 1.20-RR geometry)
  KEPT 10 (still_learning) / SUPPRESSED 1808
  VERDICT: achieved hit 39.2% does NOT beat the 50.5% floor — gate stands aside
```

**Honest read:** the re-derived target DID make price reach it — hit rate
went 1.5% → **39.2%** (26×) and expectancy improved 2.9× (−0.396R →
−0.138R) — but 39.2% < the 50.5% break-even floor at RR 1.2, so the
empirical gate still correctly stands aside.  The floor label in the verdict
is now dynamic (the old line hardcoded "4.0-RR geometry").

**Geometry re-tune sweep (§50, same 6-month window) — stop/target/z-entry
grid via the new `-Inputs` verifier override:**

```
RR     trades  hit     floor   gap     exp gross    exp @0.05
1.0    2,254   38.5%   55.0%   -16.5   -0.230R      -0.280R
1.2    1,818   39.2%   50.5%   -11.3   -0.138R      -0.188R   (previous default)
1.5    2,207   35.6%   45.0%    -9.4   -0.110R      -0.160R
2.0    2,132   32.5%   38.3%    -5.8   -0.026R      -0.076R
2.5    2,076   28.9%   33.6%    -4.7   +0.013R      -0.037R
3.0    2,008   26.0%   30.0%    -4.0   +0.042R      -0.008R   ← adopted default
3.5    2,0xx   23.1%   27.2%    -4.1   (≈ +0.05R)
4.0    2,059    1.5%   25.8%   -24.3   -0.396R      —          (original, trail ON)
```

(z fixed at 1.0 per cell, trail OFF; the 1.2 row is the swept default from
the earlier run.)  The map is monotonic: as RR rises, hit falls but the
break-even floor falls faster, so the hit-vs-floor gap narrows from −16.5 to
**−4.0** at RR 3.0 — and expectancy turns **positive gross** at RR ≥ 2.5,
reaching +0.042R gross (−0.008R at 0.05 cost) at RR 3.0, the only
positive-gross cell.  The gap bottoms at ~−4 points (RR 3.5: −4.1) before
the hit curve falls off the MFE cliff.  The committed default is now the
sweep winner: `InpTargetSigmaMult` 0.60σ (= 3.0 × stop), `InpMinTargetRR`
3.0, `InpDerivedTargetRR` 3.0, trail still OFF — reproducing on the default
run: **trades=1558, hit 25.7%, floor 30.0% (gap −4.3), expectancy +0.026R
gross, PF 1.04** — the closest the band has come to floor-clearing, but the
gate still correctly stands aside (hit is 4 points under its own floor).
At RR ≥ 2.5 the bucket pattern also flips: STRONG (deep) now outperforms
WEAK — the farther target needs the deeper entry.  The `-Inputs` sweep
tooling (writes `MQL5\Profiles\Tester\<expert>.set`, UTF-16, and points
`ExpertParameters=` at it) is a permanent verifier feature for future grids;
running it also exposed and fixed a pre-existing PowerShell array bug that
had silently disabled the verifier's `.set` purge (parenthesize each array
element or `@(a, b)` collapses to one space-joined string).

## Phase 5 — Decision, 2026-08-11

`Decision/` turns a `StrategyCandidate` into a scored, confidence-gated,
journaled decision — three modules, all pure-function/testable, all carrying
the Python production semantics transitively:

- **`ScoringEngine`** — the plan's per-axis breakdown: setup (candidate
  quality), regime alignment (exact 1.0 / same-family 0.7 / transition 0.4 /
  conflict 0.2), structure (caller-provided, neutral 0.5 default), risk (RR
  adequacy vs min RR 0.7 + max-stop fit 0.3), execution (caller-provided,
  default 1.0). Configurable weights sum to 1.0; `Explain()` emits the §10
  journal format (`REGIME=… TREND_ALIGNMENT=… SETUP_QUALITY=…
  RISK/REWARD=… EXECUTION_QUALITY=…`).
- **`ConfidenceEngine`** — faithful port of the Python `decision_engine`
  confidence math: `Classify` = `_classify_signal_strength` (strong 0.52 with
  a formal setup, 0.65 without, weak ≥ min-confidence, else WAIT),
  `DynamicMinConfidence` = the Brier-score auto-raise (0.48 base → 0.55 max,
  floor/ceil 0.25/0.10, needs ≥ 30 calibration samples), `DriftPenalty` =
  ADWIN recovery decay (0.02 over 500 steps), plus the composite↔model
  blend and a one-shot `Gate()`.
- **`TradeQualityEngine`** — the R-multiple anatomy: live MAE/MFE in R,
  +1R/+2R/+3R reached, hold bars, exit reason (Python PaperBroker R math:
  `(exit−entry)/|entry−stop|`, fallback `entry·0.001`), journaled per trade;
  per-strategy statistics answer “is this setup historically favorable
  relative to its invalidation?” with n / hit rate / avg R / expectancy /
  avg planned RR / the **break-even floor** — the exact
  `stage3_gate.break_even_floor` formula (1/(1+rr)+margin, clamp [0.10,
  0.60], fallback 0.50).

**Verification (2026-08-11):** MetaEditor compile 0 errors / 0 warnings;
Python mirror `phase5_logic_check.py` **87/87**, validated against the REAL
Python on the shared cases — `_classify_signal_strength`,
`_dynamic_min_confidence`, `_drift_confidence_penalty` (stub-constructed
DecisionEngine), and `stage3_gate.break_even_floor` — so the compiled engine
reproduces the Python confidence semantics transitively.  Strategy Tester on
SYN75: **62 passed, 0 failed**, Phases 1–4 + the band backtest re-verified
green in the same `verify_all.sh` loop.  The parity gate caught one real
first-pass deviation (a negative-Brier guard Python doesn't have — Python
just clamps) and two wrong test expectations (composite arithmetic); all
fixed and locked.  `DecisionEngine.mqh` as a separate module is deliberately  deferred: BUY/SELL/WAIT arbitration is `ConfidenceEngine.Classify` + the
  `Explain` string, and the wrapper is folded into Phase 6 so the layer isn't
  built twice.

### TradeQualityEngine real-corpus gate (R_75, 2026-08-11)

`mql5/tradequality_real_corpus_check.py` feeds **real R_75 outcomes** from the
production backtest loop (VolBand / VolMomentum / VolReversion strategies +
real BreakevenTrailBroker + RiskEngine, calibrated R_75 EGARCH, 165k ticks →
M5) through a faithful mirror of the MQL5 `CTradeQualityEngine`, replaying
each trade's intrabar path through `StartPosition`/`UpdatePosition`/
`ClosePosition`, then comparing the mirror's `Statistics()` against the
Python journal's own numbers.  **The fourth leg (2026-08-11) is the sniper
decision-engine path — `BacktestEngine.run_ticks` with the default
TraderConfig, the online ML model learning from every outcome (learn=True),
exactly as the head-to-head runs it.**  Because `run_ticks` constructs its own
broker, the harness replays the loop with a capture broker and PROVES the
replica is identical to the real `run_ticks` (fresh model, n / avg R /
signals / rejected / model version all match), then drives the mirror over
the captured sniper trades:

| strategy | n | hit | avg R | avg planned RR | break-even floor |
|---|---|---|---|---|---|
| band | 56 | 5.4% | −0.373R | 4.00 | 25.0% |
| momentum | 62 | 29.0% | −0.197R | 2.00 | 38.3% |
| fade | 8 | 50.0% | −0.178R | 0.60 | 60.0% |
| sniper (ML) | 178 | 41.6% | −0.007R | 1.90 | 39.5% |

**354/354 checks pass** — mirror n / hit / avg R / avg planned RR / break-even
floor identical to the Python journal for every strategy, per-trade return_r
and MAE/MFE match the broker's tracking to 1e-9, the MAE/MFE distributions
(mean/median/p90) are identical to the Python view, and every exit reason is
accounted for.  **The walk-forward Stage-3 kept-vs-suppressed gate now runs on
the sniper leg too (same run):** each of the 178 `run_ticks` trades is tagged
at entry by whether its per-geometry break-even floor was beatable — only
outcomes resolved strictly before that entry are visible (no lookahead), the
exact `gate_backtest.simulate_gate_walk_forward` rule the band backtest
uses.  Verdict: **mean floor at entry 39.5% (the 1.90-RR geometry), achieved
hit 41.6% BEATS it — KEPT 178 (167 proven + 11 still_learning), SUPPRESSED
0** — the sniper ML leg is the only leg that clears its own break-even floor
walk-forward (the band 25.0%, momentum 38.3%, fade 60.0% all fail), which is
exactly the signal the empirical gate needs to see: the ML calls are
edge-neutral at the floor but positive on the kept axis.  The sniper parity
gate caught a real cross-run leak: the
`features/assembler.py` EGARCH / session-filter / fingerprint detectors are
MODULE-LEVEL caches, so the harness's second run inherited the first run's
warm-up state (`fingerprint_observations` 1 → 200) and diverged by 19 trades;
`clear_assembler_caches()` before each run makes both hermetic and the
replica now matches the real `run_ticks` exactly (178 trades,
`online-logistic-v1.178`).  One harness bug was caught during the build (the
broker's MFE was captured before the closing candle updated it); the capture
now takes the final value and the MQL5 R-multiple math is locked against the
real Python corpus.  Note the journal's own verdict: on this corpus the band
geometry's 4.00 planned RR needs only a 25% hit rate to break even — it
clears nothing (5.4%), fade's 0.60 RR demands 60% (it delivers 50%), and the
sniper ML path is the only leg near its floor (41.6% hit vs 39.5%) yet still
slightly negative gross (−0.007R) — the "not tradeable yet" read holds for
all four legs.  One harness bug was caught during the build (the broker's MFE
was captured before the closing candle updated it); the capture now takes the
final value and the MQL5 R-multiple math is locked against the real Python
corpus.  Note the journal's own verdict: on this corpus the band geometry's
4.00 planned RR needs only a 25% hit rate to break even — it clears nothing
(5.4%), while fade's 0.60 RR demands 60% (it delivers 50%) — the same "not
tradeable yet" read the tester backtest produced.

**Sniper geometry re-tuned toward its MFE distribution (same gate,
2026-08-11):** the sniper leg's planned RR is 1.90 while the median MFE is
0.76R (mean 0.93R) — the target sits ~2.5× where price actually travels.  A
2-D replay sweep (stop × target multiples over the captured intrabar paths)
found exactly ONE geometry where hit ≥ its own break-even floor: target
0.60R with the stop unchanged (RR 0.60, hit 60.1%, +0.006R — and that only
clears because the floor clamps at the 60% max; raw 1/1.6+margin = 67.5%).
The literal toward-MFE target (0.76R, RR 0.76) does NOT clear (hit 53.4% vs
60.0% floor, −0.010R), and every production-legal cell (RR ≥ 1.2) is
negative.  Wired end-to-end through the real `run_ticks` path with a
research min-RR override (take_profit_rr=0.60, min_reward_risk=0,
min_primary_reward_risk=0), the re-tuned leg CLOSES the loop: **n=444, hit
62.6%, avgR +0.027R gross, avgRR 0.60, floor 60.0% — hit BEATS the floor
walk-forward (KEPT 442, SUPPRESSED 2), the model's online learning improved
on the replay (444 vs 178 trades, +0.027R vs +0.006R)**.  The catch is
structural, not accidental: **444/444 of those trades carry planned RR < 1.2
— both `RiskEngine.min_reward_risk` and the profile
`min_primary_reward_risk` veto the entire geometry in production**, and
+0.027R gross is ≈ −0.023R net at 0.05R/trade cost.  So the answer to
"does re-tuning toward MFE push hit above the floor?" is: yes, above the
clamped 60% floor, but only with a sub-1.2-RR geometry the production risk
engine deliberately refuses — and the margin is still statistically zero.
The MFE mismatch (target ≈ 2.5× median travel) is confirmed as the sniper
leg's core geometry problem; lowering the target to the MFE zone just trades
an unreachable target for an illegal (sub-minimum) RR at zero net edge.

**Exit-quality diagnosis (same gate, 2026-08-11):** the R journal now answers
"are we losing to stops, timeouts, or the trail?" per strategy:

| strategy | STOP (n / avgR) | TARGET (n / avgR) | TIME (n / avgR) | BREAKEVEN (n / avgR) | worst |
|---|---|---|---|---|---|
| band | 27 / **−1.000R** | 1 / +4.000R | 2 / +1.043R | 26 / 0.000R | **STOP** |
| momentum | 41 / **−1.000R** | 14 / +2.000R | 7 / +0.116R | — (no trail) | **STOP** |
| fade | 3 / **−1.000R** | 4 / +0.600R | 1 / −0.824R | — (no trail) | **STOP** |
| sniper (ML) | 76 / **−1.000R** | 23 / +1.900R | 79 / +0.394R | — (no trail) | **STOP** |

Every strategy's worst exit is the stop, and the MFE distribution shows why:
winners barely travel — band median MFE **1.18R** against its 4.00R target,
momentum median MFE **0.69R** against 2.00R.  The band's breakeven trail is
the one lever that already works (26 of its 53 losers are scratched to 0R —
that is why its avg loss is −0.514R instead of −1R), but the target geometry
itself is unreachable inside the hold window.  Practical reading: shorten the
targets toward what price actually travels (the MFE distribution), which is
the same direction the earlier sweep work pointed (shorter holds / smaller
σ_h multiples), rather than chasing a higher hit rate on an unreachable 4R.

**Sniper time-based exit at the hold horizon (same gate, 2026-08-11):** the
exit-quality table showed the sniper's TIME exits average **+0.394R** — the
trades that don't stop out DO drift positive, they just never reach 1.9R.
So the exit policy was re-run end-to-end (same real `run_ticks` path, same
production gates — 1R stop, RiskEngine min_reward_risk 1.2, profile
min_primary_reward_risk, take_profit_rr 1.9 still the *planned* RR for
gating; only the take-profit branch is ignored): a position exits at the
1R stop or at `signal.horizon_sec` (the mean positive-drift horizon), at
close, exactly `PaperBroker._maybe_close` minus the target branch
(`TimeExitCapturePaperBroker` in the harness):

| | n | hit | avg R | avg planned RR | Stage-3 floor | payout BE |
|---|---|---|---|---|---|---|
| baseline (fixed 1.9R target) | 178 | 41.6% | −0.007R | 1.90 | 39.5% | 41.9% |
| **time-exit (hold horizon)** | **229** | **45.9%** | **+0.059R** | 1.90 | 39.5% | 42.8% |

**The time exit flips the leg positive gross: hit 45.9% vs the 39.5%
Stage-3 floor (BEATS, KEPT 229 / SUPPRESSED 0), vs the realized-payout
break-even 42.8% (avg win +1.111R / avg loss −0.833R — BEATS), expectancy
+0.059R gross.**  Note the end-to-end feedback: with different exits the
online ML model learns different outcomes, so the run emits more trades
(229 vs 178) and the risk-rejection count shifts (2079 vs 2130).  Honest
read: gross-positive, but +0.059R gross is ≈ **+0.009R net** at 0.05R/trade
cost and −0.041R at 0.10R — statistically zero after realistic costs, same
as every other lever so far.  The time exit is not a production change (the
harness broker is research-only); it confirms the exit-quality diagnosis
— the edge lives in the first hours after entry (positive drift), and a
fixed far target simply gives it back waiting for +1.9R that never comes.

**GARCH feature freeze found & fixed (2026-08-11):** the entry-filter
sweep proved `garch_z_score` was exactly 0.00 on all 178 captured trades.
Root cause: the assembler guarded the GARCH update with
`garch.state.observations > 0` — the FIRST update was never allowed, so
observations froze at 0 and `get_forecast()` returned z=0.0 forever in
every process (caches are cleared per run).  The guard is removed
(`update()` handles warm-up internally) — `garch_z_score` /
`garch_vol_ratio` are live features again (entry |z| now spans 0.00–4.08,
median 0.75) and the sniper capture shifts 178 → 185 trades (the ML model
finally sees the feature).  Regression tests in `tests/test_assembler.py`
lock it; the periodic arch refit it activates now suppresses its
DataScaleWarning inside `_try_fit_arch`.

**Entry-filter sweep on the captured sniper set (same gate, 2026-08-11):**
with the z feature live, the sweep replays each captured trade's intrabar
path (exact PaperBroker stop-first semantics) under production-legal
targets:

- **z-depth: deep-extension entries are WORSE** — |garch_z| ≥ 1.0 →
  medMFE 0.62R, exp −0.19R; the sniper's edge is NOT in stretched entries.
- **vol-z at entry is the discriminator** — |range_z_50| ≥ 1.5 → medMFE
  0.59R, exp −0.35R (statistically extreme entry candles underperform).
- **session hours carry the edge** — UTC 12-24h entries: medMFE 0.96–1.06R;
  the top-4 hour cluster [0-3] is the worst (medMFE 0.62R).
- **drift alignment: null** — ADWIN over the M5 return series fired 0 times
  in 2,338 bars (9.5 days); no drift filter can discriminate on this corpus.
- **THE ANSWER: two cells clear the 1.0R median-MFE bar with
  production-legal targets** — `UTC 12-24h & |range_z|<1.0` (n=34, medMFE
  +1.10R, meanMFE +1.10R: hit 58.8% at RR 1.2 AND RR 1.5 vs floors 50%/45%,
  exp +0.246R/+0.267R) and `UTC 18-24h & |range_z|<1.5` (n=24, medMFE
  +1.10R, meanMFE +1.19R: hit 58.3%, exp +0.226R/+0.364R).  RR 1.5 with the
  session+vol filter is the strongest cell (+0.267R / +0.364R).  The
  target can STAY production-legal (RR ≥ 1.2) — no illegal sub-1.2-RR
  geometry — if entries are gated to UTC 12-24h with non-extreme
  entry-candle vol.  Honest caveat: n=34/24 is small (one month-ish) —
  the vol-z × hour interaction needs the next corpus growth to confirm.

**Time-exit × shallow-fade entry filter, end-to-end (same corpus,
2026-08-11):** the two levers combined IN THE RUN LOOP — the entry filter
gates signals after the risk engine so the online ML model never learns
from filtered trades (the harness's new `entry_filter` hook, default
None), with the time-exit broker exiting at the hold horizon:

| run | n | hit | gross | net@0.05 | net@0.10 | payout BE |
|---|---|---|---|---|---|---|
| time-exit baseline | 208 | 41.8% | −0.018R | −0.068R | −0.118R | ✗ |
| **+ UTC12-24h/rz<1.0** | **149** | **50.3%** | **+0.142R** | **+0.092R** | **+0.042R** | **✓** |
| **+ UTC18-24h/rz<1.5** | **77** | **51.9%** | **+0.191R** | **+0.141R** | **+0.091R** | **✓** |

**Net expectancy survives realistic costs — the first cell in the whole
research program to clear 0.05–0.10 R/trade.**  UTC18-24h/rz<1.5 is
+0.141R net@0.05 (77 trades); the more robust UTC12-24h/rz<1.0 (149
≈15/day) is +0.092R net@0.05 and still +0.042R at 0.10 cost.  Both beat
the 39.5% Stage-3 floor and the realized-payout break-even; the
walk-forward gate would trade them (KEPT 148/149 @50.0%, KEPT 77/77
@51.9%).  Caveats: single 9.5-day window (the +0.160R/+0.209R lift vs
baseline is the robust read, not the absolute level), and the time exit
remains research-only.  The hour filter uses the true entry-bar hour
from `snapshot.epoch` — production-feasible.

**Session-vol gate × depth cap, with realized DRAWDOWN (10.5-day corpus,
2026-08-11):** the band's drawdown-reducing depth cap (|garch_z| ≤ 1.5,
entry-bar return vs EGARCH sigma — the same edge-depth axis as the band's
|z|/z_entry) layered on the sniper session-vol gate, all time-exit,
in-loop filtering, drawdown on the realized cumulative-R curve:

| run | n | hit | gross | net@0.05 | net@0.10 | maxDD | worst streak |
|---|---|---|---|---|---|---|---|
| time-exit baseline | 208 | 41.8% | −0.018R | −0.068R | −0.118R | 18.28R | 8 |
| + sv 12-24h/rz<1.0 | 149 | 50.3% | +0.142R | +0.092R | +0.042R | 5.71R | 5 |
| **+ svcap …/gz≤1.5** | **146** | **52.1%** | **+0.161R** | **+0.111R** | **+0.061R** | 5.85R | 5 |
| + evcap 18-24h/rz<1.5/gz≤1.5 | 77 | 50.6% | +0.186R | +0.136R | +0.086R | 6.80R | 4 |

**The depth cap adds a small expectancy lift on top of the session-vol
gate (svcap +0.161R gross / 52.1% hit vs sv +0.142R / 50.3%) but the
3.2× drawdown cut (18.28R → 5.71R) comes almost entirely from the gate
itself** — the band's cap-vs-drawdown relationship did not transfer to
the sniper side (5.85R vs 5.71R).  Best balanced cell: **svcap — 146
trades (~14/day), +0.111R net@0.05, +0.061R net@0.10, KEPT 146/146**.  The
6-month combined measurement still requires porting the sniper ML path to
the tester (Python corpus is ~10.5 days).

**Why deep fades are the drawdown machines (6-month tester, RR 1.2,
2026-08-11):** per-trade exit-reason / vol-regime-at-entry capture plus a
deep-vs-shallow profile now in `BandBackTests`:

| bucket | n | hit | exp | sumR | hold | MFE | vol@entry | stop/target/time |
|---|---|---|---|---|---|---|---|---|
| shallow ≤1.5 | 196 | 41.3% | −0.091R | −17.8R | 2.6b | +1.43R | 1.13 | 59/41/0% |
| mid 1.5-2.5 | 417 | 40.8% | −0.103R | −43.0R | 1.2b | +1.40R | 1.13 | 59/41/0% |
| deep >2.5 | 1,183 | 40.1% | −0.119R | **−140.2R** | 2.9b | +1.45R | 1.13 | 60/40/0% |

**The deep fades are NOT different animals — they bleed by VOLUME:**
identical hit/MFE/vol-regime/exit-mix across depth, but 66% of the trades
(1,183/1,796) at marginally worse expectancy → 71% of the −202R bleed
(−140.2R sumR).  The depth-cap drawdown cut was mechanical
count-scaling, not a tail fix.  **No time dimension to fix: 0% of trades
reach the 1h expiry (all resolve by stop/target within ~1-3 bars).**  A
dead-trade time exit (exit at close when MFE < 0.4R after N bars) never
fires at N=4, and at N=1 it makes things WORSE (exp −0.121R, maxDD
227.8R vs 204.8R).  The tail is entry-side: hit toward the 50.5% floor,
not exits.

**Depth-cap grid on the RR-3.0 DEFAULT geometry (6-month tester,
2026-08-11):** confirms the cap HURTS at RR 3.0 and corrects the old
"deep beats shallow" claim:

| cap | n | hit | exp gross | exp@0.05 | maxDD |
|---|---|---|---|---|---|
| OFF (default) | 1,503 | **25.9%** | **+0.039R** | −0.011R | 81.0R |
| 2.0 | 378 | 23.0% | −0.079R | −0.129R | 48.0R |
| 1.5 | 181 | 23.8% | −0.050R | −0.100R | 36.0R |

**The cap destroys the RR-3.0 geometry's only positive-gross cell
(+0.039R → −0.079R/−0.050R, hit 25.9% → 23.0-23.8%).**  The direction
was predicted, but the supporting claim was wrong — "STRONG 25.8% vs
WEAK 17.1%" rested on a 60-trade WEAK bucket that flips on re-run (now
28.3%, +0.133R; STRONG 25.8% stays stable).  The large-n depth profile
shows the opposite: shallow ≤1.5 → 28.0% hit, **+0.119R**, +20.0R sumR;
mid → 28.0%, +0.120R, +40.0R; deep >2.5 → 24.9%, −0.002R — the shallow
and mid fades are the positive buckets.  Caveat: the seeded geometry
sweep reshuffles the RNG when entries are blocked, so capped runs aren't
pure subsets — the measured cap cells are negative as-is.  Drawdown still
drops with the cap (81 → 36-48R, mechanical count-scaling).  Cap stays
default OFF at both geometries — it trades expectancy for drawdown.

**Edge-depth cap on the band entries (6-month tester, RR-1.2 geometry,
2026-08-11):** the hypothesis was that blocking deep-extension entries
(depth = |z|/z_entry > ~2) lifts hit from 39.2% toward the 50.5% floor.
`BandBackTests` now carries `InpMaxEdgeDepth` (0 = OFF) + a per-cap
depth-split report + a `depth_fail` attrition counter.  The RR-1.2 grid:

| cap | n | hit | exp gross | floor | maxDD |
|---|---|---|---|---|---|
| OFF | 1,796 | 40.4% | −0.112R | 50.5% | 204.8R |
| 2.0 | 198 | 40.4% | −0.111R | 50.5% | 32.4R |
| 1.5 | 404 | **41.1%** | **−0.096R** | 50.5% | **42.2R** |
| ≤1.25 slice | 86 | **46.5%** | **+0.023R** | 50.5% | — |

**Verdict: the hypothesis does NOT clear the floor — but the cap is a
real risk lever.**  Depth > 2.0 blocking leaves hit at 40.4%, identical to
the full set — the deep trades were never dragging hit down at entry; the
"45.3% vs 39.2%" was a 64-trade WEAK-bucket sample that flips between
runs (37.9% / 41.7% / 45.9%).  Every depth cell misses the 50.5% floor;
the tightest slice (depth ≤ 1.25, n=86) is the best RR-1.2 cell ever
(46.5% hit, +0.023R gross ≈ −0.03R net) but still 4 points short.  The
cap's real effect is tail risk: max drawdown collapses 204.8R → 42.2R
(cap 1.5) → 32.4R (cap 2.0), ~6×, with expectancy flat — the deep fades
are the drawdown machines.  Cap stays default OFF; the drawdown lever is
available via `-Inputs InpMaxEdgeDepth=1.5`.

**Trail sweep at the derived 1.2-RR target (6-month tester, 2026-08-11):**
can a trail_frac stop RACING the target (arm at 0.8×1.2 = 0.96R) while
still scratching −1R losers?  No — the trail races the target at EVERY
frac:

| frac | arm | n | hit | exp gross | avg loss | maxDD |
|---|---|---|---|---|---|---|
| 0.0 | off | 1,796 | **40.4%** | **−0.112R** | −1.000R | 204.8R |
| 0.2 | 0.24R | 1,902 | 2.1% | −0.109R | −0.137R | 208.2R |
| 0.4 | 0.48R | 1,900 | 2.4% | −0.199R | −0.234R | 380.0R |
| 0.5 | 0.60R | 1,885 | 2.5% | −0.260R | −0.297R | 489.8R |
| 0.6 | 0.72R | 1,861 | 3.0% | −0.292R | −0.337R | 543.2R |
| 0.7 | 0.84R | 1,831 | 2.8% | −0.347R | −0.392R | 634.8R |
| 0.8 | 0.96R | 1,832 | 3.8% | −0.367R | −0.429R | 672.0R |

**Verdict: even at 0.8 (arming 0.96R, 80% of the way to the 1.2R target)
the trail destroys the hit rate (3.8% vs 40.4%) and expectancy degrades
monotonically.**  The breakeven conversion is real (avg loss −1.0 →
−0.14R at 0.2) but trades that arm the trail and would reach 1.2R almost
always wick back through entry first — the same-candle stop-first exit
scratches them at 0R.  Max DD also worsens with the trail (204.8 →
672R): steady −0.3R near-scratch bleed compounds instead of clean −1R
losers.  Trail stays OFF (0.0) — the default is confirmed correct.  The
untested escape hatch: the tester's trail exit lacks the closed-candle
grace the Python system already applies to stops — same-candle wick
jitter scratches valid plans; a closed-candle trail exit is the natural
next experiment.

## Phase 6 — Risk, 2026-08-11

`Risk/` gives the plan's RiskEngine final authority over the Phase-5 decision
output — five modules, all deterministic and Python-parity-locked:

- **`PositionSizer`** — two layers: `Stake` is the exact Python RiskEngine
  stake formula (`risk_budget × (0.55 + 0.70·quality)`, floor 0.35, × the
  Stage-3 empirical scale, capped at 1.25× budget; paper-only scale → 0), and
  `Lots` is the plan's MT5 conversion (`stake / (|entry−stop| ·
  tick_value/tick_size)`), floored to the symbol's volume step and clamped to
  [vol_min, vol_max] — the SymbolAdapter contract feeds the specs.
- **`RiskLimits`** — the Max* table (Constants defaults): per-trade risk,
  daily loss, daily drawdown, equity drawdown, open positions, total
  exposure, consecutive losses (the Python −0.10R scratch threshold), trades
  per hour/day, plus the EMERGENCY_STOP flag. `AnyHardLimitBreached()` is the
  plan's TRADING DISABLED condition; `SyncWindow` reports the session-day roll.
- **`DrawdownProtection`** — Python-parity fractions (daily loss from
  day-start, intraday peak-to-trough, all-time equity DD) and `Halted()`
  returning the FIRST breached limit — never auto-overridden.
- **`ExposureManager`** — account-mode aware (reads `ACCOUNT_MARGIN_MODE` at
  runtime, `SetMode` override for tests): netting forbids a second position
  of EITHER direction, hedging allows one per direction; exposure fraction
  vs the max-exposure limit.
- **`RiskEngine`** — the authority path: consumes the Phase-5
  `StrategyCandidate` (confidence / reward_risk / direction / entry / stop /
  signal-strength verdict), applies the Python-parity veto gates with named
  reasons (max open, consecutive-loss breaker, daily loss, confidence below
  min, reward/risk below min, extreme volatility z, exposure, EMERGENCY_STOP)
  plus the **decision-layer verdict gate** (MQL5 extension — Python has no
  verdict bucket): a WEAK verdict is vetoed BEFORE the sizer runs when the
  gate is on (`SetVetoWeakSignals`, default ON — only STRONG signals trade),
  and a WAIT verdict is vetoed unconditionally (a WAIT candidate must never
  be sized, even if its raw confidence clears the minimum).  Then sizes the
  approved trade into `RiskVerdict{approved, lots, stake, reasons}` — the
  exact input Phase 7's execution layer consumes.

**Verification (2026-08-11):** MetaEditor compile 0 errors / 0 warnings;
Python mirror `phase6_logic_check.py` **45/45**, validated against the REAL
Python `RiskEngine` — the stake formula on 6 scenarios, each veto gate's
reason, the −0.10R streak threshold, `daily_drawdown_fraction`, and
register_open counting — so the compiled engine carries the research-lab risk
semantics transitively.  Strategy Tester on SYN75: **45 passed, 0 failed**
(the 5 new decision-verdict checks: WEAK vetoed with the named reason, WAIT
never sized, STRONG approved with the gate on, WEAK passing when the gate is
off, WAIT veto persisting regardless),
Phases 1–5 + the band backtest + the structure live gate re-verified green in
the same `verify_all.sh` loop.  Three MQL5-side issues caught during the gate:
MQL5 cannot return object references (sub-engines are public members —
`engine.limits` / `engine.dd` / `engine.exposure`), the reason trail now always
names the specific breached limit, and the drawdown day-window init is the
caller's job (`SyncState` does it on first sync / day roll).  The plan's gate
cases are all test-locked: sizing math, hard-limit breach → disabled, netting
forbids the second position, EMERGENCY_STOP blocks everything.

## What is deliberately NOT here

- No unvalidated strategy logic. The band geometry, EGARCH dynamics, and
  Stage-3 floor live in Python where they are measured and tested; the five
  research strategies here are skeletons with hypothesis headers, hard-disabled
  until they pass the same walk-forward gates as the band leg. Porting
  unvalidated strategy code into MQL5 is how "grid booster" EAs get created —
  this repo refuses to do that (the geraked repo's own warning).
- No position sizing beyond the volume the Python risk engine already computed
  (clamped to the broker's min/step/max). Sizing is an evidence-based decision
  made in the research lab, not inside the EA.
