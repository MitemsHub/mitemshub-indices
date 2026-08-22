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
  table; unconfigured = disabled.  The email subject is parsed from
  `verify_all.ps1`'s machine-readable summary line — `[VERIFY] summary
  ok=1 rows=N green=N red=N skip=N` (green) or `ok=0 ... failed=SuiteA,SuiteB`
  (red) — so a failing row like the P10-A STRICT Δ11 breach is named in the
  subject without scraping the human table.  The old `ALL SUITES PASSED` /
  `N suite(s) NOT green` / `PRE-FLIGHT FAILED` text regexes remain as
  fallbacks for runs that never reached the summary (pre-flight throw).
- **Mutual pause with the live tick collector**: every tester run closes the
  live terminal (`Stop-Process terminal64`), which the collector otherwise
  reads as a feed loss and reconnects against — and could attach to the
  *tester* instance and pollute the corpus with modeled ticks.  Before the
  first suite, `verify_all.ps1` writes `.data/verify_pause.flag`
  (`VERIFY_PAUSE_PATH` in `src/synthetic_trader/data/continuous_collector.py`)
  and waits (≤20s) for the collector's status file to report `paused_by`;
  the collector stands down completely while the marker is fresh — no tick
  polling, no stall warnings, no reconnects — and restarts its stall timer
  on resume.  The marker is removed after the terminal is restored (and on
  the no-restore path), and a marker older than 2h is ignored, so a crashed
  verify self-heals instead of standing the collector down forever.

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
- **Stage-3 floor verdict** — the gate's own `VERDICT: achieved hit X%
  BEATS / does NOT beat the Y% floor` line is a contract too.  It must be
  PRESENT (a refactor dropping the gate block fails the suite); the verdict
  must be internally CONSISTENT with its own numbers (a declared `BEATS`
  with hit below the floor — or `does NOT beat` with hit above it — is a
  FLIP bug, not an improvement, and fails with `floor verdict FLIP:`); and
  the floor must sit in [20%, 60%] (the 1/(1+RR)+margin band for the RR
  1.0–3.5 geometries this suite measures — outside that, the break-even
  math regressed).  A ±0.15pp tolerance absorbs the suite's print rounding
  (it decides on raw doubles, prints 1-decimal).  The healthy verdict state
  rides in the Detail column (`floor-gate: hit 25.4% does NOT beat 30%`),
  so a flip is visible in every run's summary.
- **Vol-regime split contract** — the suite also prints a vol-regime split
  at entry (`vol_ratio_entry = prev_sigma / sigma_ema`, cells
  `vol<=1.25` / `vol>1.25`, each with n / hit / exp / stop-outs) to answer
  whether the book drifts into high-vol-regime entries.  The verifier parses
  it and flags when the `vol>1.25` cell becomes a MEANINGFUL SHARE of
  trades: `>=20%` of the book with negative expectancy fails the suite
  (`high-vol entries diluting the edge`), and `>=35%` fails unconditionally
  (`the vol cell IS the book` — at that point it is no longer a diagnostic
  cell but the strategy, and its floor needs its own validation).  A
  large-but-positive share is reported in the Detail line, not failed
  (measured 2026-08-12 default run: 0.7% share, +0.200R).  Each vol cell
  prints ONLY when it has trades (the suite skips empty buckets), so a
  missing `vol>1.25` row means zero high-vol trades — normal; a missing
  split HEADER is a refactor regression and fails like the other contracts.
- **Machine-parseable depth profile + floor verdict** — the suite also
  prints one `[BANDBT] DEPTHPROFILE` line (all 5 cumulative caps in one
  line: `n=... hit=... exp=... share=... total=...`, empty buckets emitted
  as n=0) and one `[BANDBT] FLOORVERDICT` line
  (`floor=... achieved=... verdict=BEAT|NOT_BEAT mean_rr=...`).  These are
  the robust contract lines for the BUCKET-COMPOSITION gate: each cap's
  share of the book must stay in the measured bands — sweep ON/OFF across
  5 seeds and TARGET/TIME modes span <=1.25 10.7-12.4%, <=1.50
  20.9-24.7%, <=2.00 46.7-48.6%, <=2.50 71.7-74.3% — so a composition
  shift (a refactor letting deep trades dominate, or the shallow bucket
  collapsing) FAILs the loop with `bucket composition shifted`.  Guarded
  by total>=50 so thin windows don't false-fail.  The machine lines must
  AGREE with the parsed per-row lines (per-cap n and total cross-checked —
  a mismatch is a print bug) and FLOORVERDICT must agree with the human
  VERDICT (BEAT <-> BEATS / NOT_BEAT <-> does NOT beat).  Missing machine
  lines FAIL the suite.  The healthy state rides in the Detail column
  (`depth-comp: <=1.25 12.4% | <=1.50 24.7% | <=2.50 71.7% (total 693)`).

On a healthy run the summary rides in the Detail column (`depth-split: 5
cells, <=1.25 hit 28.1%/exp 0.124R, <=2.00 hit 27.7%/exp 0.106R ... |
floor-gate: hit 25.4% does NOT beat 30% | vol-split: <=1.25 n=1527
hit=25.3% exp=+0.014R; >1.25 n=10 hit=30.0% exp=+0.200R (0.7% of
trades)`); on violation the suite shows `FAIL ... | DEPTH-REGRESSION:
<why>` and the overall loop exits 1.
Verified: healthy run PASSes with the summary; missing-report /
collapsed-hit / partial-table fixtures, all floor-verdict branches
(flip-to-BEATS, flip-to-NOT, missing block, missing verdict line, floor
out of band), and all vol-split branches (meaningful share + negative exp,
share >= 35%, missing header, missing lo row, zero high-vol cell, large
positive share, missing DEPTHPROFILE, missing FLOORVERDICT, machine-vs-human
verdict mismatch, deep-dominant composition, and thin-window composition
skip) FAIL/PASS with the specific cause (`verify_volsplit_fixtures.ps1`).

**Seed noise caveat — the RNG-reshuffle confound (measured 2026-08-12):**
all of the above tables come from ONE seed of the suite's per-signal
geometry sweep (`MathSrand(InpGeomSeed)` draws z_entry in [0.7, 1.6] and
stop_mult in [0.15, 0.35] — target = 3.0 x stop — for every gated signal,
so the seed decides which signals pass the z gate, their stop width, and
their edge-depth bucket).  `mql5/seed_sweep.ps1` runs the RR-3.0
cap-2.0 cell across 5 seeds (7/42/123/777/2024, ~25s each, sniper gate
skipped) and the spread is material:

| seed | <=1.25 exp | <=2.00 n/hit/exp | <=3.00 exp | vol>1.25 n/exp |
|---|---|---|---|---|
| 7 | −0.038R | 323 / 25.4% / +0.018R | −0.011R | 8 / −1.000R |
| 42 (default) | +0.256R | 329 / 25.8% / +0.033R | +0.017R | 10 / +0.200R |
| 123 | −0.241R | 317 / 23.0% / −0.079R | −0.089R | 10 / +0.200R |
| 777 | −0.257R | 298 / 25.8% / +0.034R | −0.025R | 6 / +0.333R |
| 2024 | +0.222R | 324 / 27.8% / +0.111R | +0.109R | 9 / −0.111R |

Cap-2.0 across seeds: hit 23.0–27.8% (mean 25.6%, spread 4.8pp); exp
−0.079R to +0.111R (mean +0.023R, spread 0.190R — ~8x the mean, so a
single seed's exp is NOT distinguishable from noise); n 298–329 (±5% —
entry COUNT barely moves; the seed changes WHICH signals and their
geometry).  The shallow <=1.25 cell is far worse: exp flips sign across
seeds (−0.257R to +0.256R).  The depth-split bands and the vol-share
contract survive every seed (no false failures), but any positive-EXP
conclusion on a cell should be re-checked across >=3 seeds before trusting
it; seed 42 (the default) sits near the cap-2.0 mean, not at an extreme.

**Seed-sweep depth gate (`verify_all.ps1 -SeedSweep`):** the single-seed
contract above certifies on ONE draw, so the loop now offers the strict
multi-seed gate as an opt-in switch.  `-SeedSweep -Seeds "7,42,123,777,2024"`
re-runs BandBackTests once per seed (~25s each, compile once — inputs arrive
via the .set and `-Inputs` overrides pass through with InpGeomSeed swept) and
fails the suite when the depth-split cell MEANS are not stable across seeds:
(1) mean exp < +0.05R — the cell is not positive after seed averaging;
(2) exp spread > 0.25R — a quarter-R swing between seeds; (3) a small
positive mean (< 0.10R) whose spread exceeds 3x the mean — noise, not
signal.  Both reference cells (shallow <=1.25 and the cap-2.00 doc cell) must
pass; hit spread is reported but not gated (4.8pp at n~320 is counting noise,
exp is the decision metric).  Verified on the real 5-seed run: the gate
FAILS exactly as it should — cap-2.00 mean +0.023R < floor, spread 8.1x the
mean; shallow mean −0.012R, spread 0.513R — with per-seed numbers
byte-identical to `seed_sweep.ps1`.  The verdict is a `SeedSweep` row in the
summary (FAIL trips the loop exit), and the pure verdict logic is
fixture-tested (`verify_seedsweep_fixtures.ps1`, 8 branches).  The gate is
opt-in: the scheduled single-seed run keeps its existing contract, and a
re-tuned cell that survives seed averaging will PASS this gate.

**Pure subset test — geometry sweep OFF (fixed z_entry=1.0, stop 0.20 sigma,
target 0.60 sigma = 3.0R), TARGET mode, 6-month (2026-08-12):** with
`InpGeomSweep=false` there is no RNG at all (MathSrand is never consumed),
so `depth = |z|/z_entry = |z|` is a pure market measure and the rows are
deterministic — verified byte-identical across seeds 42 and 7.  The
shallow-fade edge is REAL, not a sweep artifact, and is actually CLEANER
with the confound removed:

| depth bucket (sweep OFF) | n | hit | exp | sweep-ON (seed 42) exp |
|---|---|---|---|---|
| <=1.25 | 54 | 27.8% | +0.111R | +0.256R |
| **<=1.50** | **109** | **27.5%** | **+0.101R** | **+0.053R** |
| <=2.00 | 220 | 23.2% | −0.073R | +0.033R |
| <=2.50 | 339 | 24.2% | −0.032R | +0.038R |
| <=3.00 | 456 | 24.3% | −0.026R | +0.017R |
| verdict | | hit 24.4% | does NOT beat 30% | |

Shallow <=1.50 (|z| in [1.0, 1.5]) is the ONLY positive bucket — hit
27.5%, exp +0.101R — while every deeper bucket is negative (−0.073R at
<=2.00, −0.026R at <=3.00): the pure depth profile is monotone (edge in
shallow, bleed in deep), exactly the pattern the depth-cap work targeted.
The sweep was DILUTING the shallow edge (its random z_entry divisor
rebuckets trades: sweep-ON shallow mixes in deeper trades that drew a
high z_entry, and a high z_entry also raises the entry bar).  Fixed
geometry also shrinks the funnel (456 vs 693 trades).  BUT the floor
verdict still stands aside: overall 24.4% vs 30%, and even shallow-only
27.5% is 2.5pp short of the 30% floor — within ~0.6 sigma at n=109
(can't reject hit >= 30% statistically), but the measured value is below
and the gate correctly refuses.

### Sniper walk-forward gate contract (SniperGate row)

The band's depth-split contract covers the MQL5 tester side; the sniper
leg's walk-forward gate lives in the Python harness, so its regression gate
is a second suite row: `verify_all.ps1` runs
`python mql5/svcap_recheck.py --gate-check` (one real `run_ticks` pass of
the reference gate-clean svcap cell — UTC 12-24h & |range_z|<1.0 &
|garch_z|<=1.5, time-exit — ~3-5 min, corpus replay, no MT5 dependency) and
honors its `[GATECHECK]` verdict + exit code:

- **PASS** — kept/suppressed split sane (reference run 2026-08-12:
  kept=147/147, suppressed=0, +0.160R net@0.05).
- **FAIL** (loop exits 1) — suppressed fraction > 10% of the cell (the
  walk-forward gate blocking a previously gate-clean cell), zero kept
  trades, or net@0.05 below −0.10R (expectancy regression).
- **SKIP** — corpus too thin (< 30 cell trades) or python missing; neither
  fails the loop (a fresh checkout must not false-fail, but the check is
  armed on this machine).

The row renders in the summary table as `SniperGate - PASS|FAIL` (Compile
"-" = Python row, no MQL5 compile).  Add `-SkipSniperGate` to a run to
skip the ~3-5 min Python pass.  Verified end-to-end 2026-08-12: healthy
run emits `[GATECHECK] PASS` (n=147 kept=147 suppressed=0 (0.0%)) and the
loop reports `ALL SUITES PASSED (compile + Strategy Tester + sniper gate
contract)`; the FAIL/SKIP verdict branches are unit-tested in
gate_verdict() and the PowerShell parse (last-`[GATECHECK]`-line-wins) is
fixture-tested.

### Paper->live execution parity contract (ExecutionParity row)

The Python engine can execute an approved call three ways, and they must
behave as ONE execution layer: the **simulated** backend (forward-demo
paper fills), the **MT5 python-API** backend (`Mt5LiveExecutionBackend` —
the Python CTrade-equivalent: FOK market order, broker SL/TP, modify/close
by ticket, retcode-verified), and the **MQL5 SynthCallExecutor EA** (polls
the call file `ea_emitter` writes and executes via CTrade).  `verify_all.ps1`
runs `python mql5/execution_parity_check.py` (pure Python — the live
backend runs against `FakeMetaTrader5`, an in-memory CTrade-equivalent
simulator with ask/bid fills, position open/close/modify, and configurable
reject retcodes) and honors its `[PARITY]` verdict + exit code:

- **PASS** — deterministic buy/sell signals replayed through the simulated
  and live backends agree on EVERY decision: submit acceptance,
  open-position counts after each submit/candle/shutdown, and per-outcome
  direction/entry/exit/return_r/won/close-time (reference run 2026-08-12:
  compared=40 agreed=40 mismatches=0, trades=3 covering target / stop /
  expiry exits, broker-rejection probe ok, EA contract 3/3).
- **FAIL** (loop exits 1) — any disagreement, the live path accepting a
  broker-rejected order, or an EA call record that drifted from the
  executed levels.

Two things the parity work fixed/added on the live backend: `open_positions_count()`
now re-syncs with the broker instead of returning the stale submit-time
snapshot (a mid-session stop/target close left the count at 1 while the
paper side correctly read 0), and the EA-contract check
(`check_ea_contract` in `src/synthetic_trader/execution/parity.py`)
proves `build_call_record` emits exactly the direction/entry/stop/target/volume
the Python backends executed — so the MQL5 path shares one execution
contract.  Add `-SkipExecutionParity` to skip the ~2s check.  Unit-tested
in `tests/test_execution_parity.py` (simulator fill/close/modify/reject
semantics + replay parity + drift detection).

### Real-corpus gate contracts (RealCorpus row, 2026-08-15)

`verify_all.ps1` now runs the Phase-6/7 real-corpus harnesses as a third
Python contract row — the same stateful-replay gates the individual phases
were validated with, asserted on EVERY verify run (fast: ~3s per invocation
on the current corpus):

- **`phase6_real_corpus_check.py` (risk layer)** — `--mode aligned` must
  report **100% veto agreement AND 100% stateful AND stake parity**
  (measured 2309/2309); `--mode defaults` is parse-only (the ~17%
  disagreements are documented config drift — Python stricter on
daily-loss/consecutive, MQL5 adds trades/day + trades/hour + WEAK-veto
caps).
- **`phase7_real_corpus_check.py` (execution layer)** — `--mode aligned`
  must report **100% entry+exit parity** and **0 min-RR float-boundary
disagreements** (measured 1014/1014, rr 0); `--mode defaults` must keep
  the management edge — the closed-candle grace + BE trail lane must beat
the Python wick journal on the same entries (`sumR_mq > sumR_py`, measured
+104.6 vs −82.4) and the grace/trail conversions must be present
(grace_saved + trail_converted > 0, measured 201 + 259).

A regression in ANY contract — a refactor that breaks the mirror, the
grace, or the trail — fails the loop like the depth-split/sniper gates.
The row renders as `RealCorpus - PASS|FAIL`; add `-SkipRealCorpusGate` to
opt out.  Both FAIL branches (parity < 100% and the defaults edge flip)
were verified end-to-end on 2026-08-15.

### Phase-8 analytics gate (Phase8Gate row, 2026-08-15)

`verify_all.ps1` also runs `phase8_analytics_check.py` as a fourth Python
contract row.  The harness replays the production band backtest on the
real R_75 corpus, REQUIRES its replication to match the CLI
`backtest-vol --mode band` (`[PARITY] verdict=MATCH` — the "this is a real
band backtest" guarantee), feeds the captured OutcomeRecords through the
Phase-8 analytics stack, and emits machine lines the gate parses:

- **band row** — `n / hit / exp / sumR / maxDD / floor / beats` must parse,
  the floor must sit inside the [10,60] clamp, and the beats verdict must
  be consistent with `(n >= min_samples AND hit >= floor)`.
- **bucket split** — `strong n + weak n` must equal the total `n` (the
  confidence buckets must partition the trade set; a refactor that drops a
  trade from the split fails).
- **exit split** — `stop + trail + target + time` must equal `n` (every
  outcome must carry an exit reason).
- **parity** — `MATCH` is required; a mismatch means the analytics are
  being measured on something that is no longer the real band backtest.

The row renders as `Phase8Gate - PASS|FAIL`; add `-SkipPhase8Gate` to opt
out.  Both branches were verified end-to-end on 2026-08-15: PASS on the
measured numbers (n=28, floor 25%, beats=no, strong 18 / weak 10) and FAIL
when the bucket partition was broken (strong 17 + weak 10 != 28).

### Phase-6 risk-wiring gate (Phase6RiskGate row, 2026-08-16)

`verify_all.ps1` runs a dedicated EA tester pass as its own contract row to
prove the integrated EA's hard risk limits (§12 "TRADING DISABLED") actually
fire.  P10-B exposed a defect where the EA fired 523 trades with **0 risk
vetoes**: outcomes were never registered, so the consecutive-loss / daily-loss
/ equity-drawdown breakers saw 0 losses forever — and the P10-A gate masked
it because the aligned 300s config expects vetoes=0.  This gate re-runs the
exact P10-B configuration and fails the loop visibly if the vetoes are gone
again:

- compiles + stages the integrated EA wrapper (`Phase10IntegrationTests`),
- runs it in the Strategy Tester at **`InpBarSec=60` (M1)** with the Python
  default risk (consec 4, daily 2% = 0.02 fraction, equity-DD disabled) —
  the same `-Inputs` as the documented P10-B row,
- parses the `[PHASE10]` machine line **scoped to `bar_sec=60`** (the log
  accumulates all of the day's runs, so a plain "last line wins" parse would
  mis-read the P10-A 300s line and vice-versa — `Get-Phase10TradesLine`
  pairs each `trades=` line with its own `bar_sec=` line),
- **FAILS if `risk_vetoes = 0`** with a meaningful trade count (>0) — the
  exact P10-B regression signature (523 trades / 0 vetoes) — and also fails
  on a 0-trade run so the check can't pass vacuously.

The P10-A gate now uses the same bar_sec-scoped parser for its 300s line, so
the two EA rows coexist in one log without cross-reading.  The row renders as
`Phase6RiskGate - PASS|FAIL`; add `-SkipPhase6Gate` to opt out.  Verified
end-to-end on 2026-08-16 (17-day window): PASS with the live run at **241
trades / 325 vetoes / 0 rejects** (P10-B reference 238 / 318 / 0), and the
FAIL branch proven on the regression signature (523 trades / 0 vetoes ->
FAIL, 0 trades -> FAIL).

### Phase-10 P10-E real-tick sign gate (Phase10ESignGate row, 2026-08-16)

The P10-E OHLC stress row proved the tester's price model can **flip the EA's
PnL sign**: the same window/config that loses **−36.964R on real ticks**
(Model=1) shows **+55.502R under 1-min OHLC** (Model=2).  Only the real-tick
basis is trustworthy for the band's wick-sensitive geometry, so this row
makes the real-tick sign a hard contract:

- parses the integrated EA's `[PHASE10]` machine line **scoped to
  `bar_sec=300`** (the suite loop's Model=1 real-tick run — no extra tester
  pass needed; the Phase-6 gate's 60s line and any OHLC-stress 300s line are
  kept separate by `Get-Phase10TradesLine`),
- runs the CLI band reference on the repaired corpus (`backtest-vol --mode
  band @300s`, the same command P10-A uses),
- **FAILS loudly if the EA's real-tick sumR disagrees in sign** with the CLI
  reference expectancy — the P10 matrix locks R_75 NEGATIVE on the
  calibrated real-tick basis, so a flip means the calibration/geometry/cost
  basis changed materially and must be deliberately re-baselined, not
  carried silently,
- also fails on a 0-trade run, an exactly-0 sumR, an exactly-0 reference, or
  a missing machine line — it can never pass vacuously.

The row renders as `Phase10ESignGate - PASS|FAIL`; add
`-SkipPhase10ESignGate` to opt out.  Contract-location rule identical to the
Phase-6 row: SKIPs when `Phase10IntegrationTests` isn't in the run's suites.
Verified end-to-end on 2026-08-16 (17-day window, alongside the P10-A row):
**PASS — real-tick sumR=−36.964 (n=98) agrees in sign with CLI exp=−0.376
(both NEGATIVE)**; the FAIL branch proven on synthetic flips (EA +36.964 vs
ref −0.376 -> FAIL, and the reverse -> FAIL) plus the degenerate guards.

**Why the grace is band-specific (2026-08-18).**  `_probe_sniper_ohlc.py`
replays the real captured sniper entry set (249 entries, no trail) under
four price models — WICK-M5 (real ticks), CLOSE-M5, CLOSE-M1 (the true
TestModel=2 analog), and WICK-M1 (extreme-based at the tester's 1-min
resolution, which brackets the close-vs-extreme interpretation).  The
sniper does **NOT flip** in any lane: sumR +88.16 (wick) vs +86.75 (both
M1 lanes, Δ−1.41R); WICK-M1 ≡ CLOSE-M1 in sumR, with only 4/129
stop-outs resolving a few minutes later under close semantics and **0
saved** by the closed-candle grace at 1-min resolution.  Compare the
band's +92.47R Model=2 swing: the closed-candle grace is a property of the
band's wide stop geometry, not a general wick-save the sniper can harvest —
the sniper's tight 1R stops are close-throughs, so the wick-save ceiling
must never be misread as sniper-harvestable.

### Calibration-sanity gate (CalibrationGate row, 2026-08-16)

`verify_all.ps1` runs `calibration_sanity_check.py` as a sixth Python
contract row.  The harness loads the on-disk EGARCH calibration JSONs
(`data/garch_calibration/r_75.json`, `r_100.json` — the exact files the
live engine and the band reference load on startup) and requires each fit to
be usable:

- the file exists and parses;
- `convergence=True` (a degenerate / all-basins-rejected fit reports False
  and the loader silently falls back to default priors — the gate makes
  that visible);
- NOT rejected by `_params_at_bounds` (bound-pinned, no-clustering,
  absurd-NLL, or absurd long-run-ratio fits); and
- `vol_ratio` inside the healthy band `[0.02, 50]` (criterion-3 semantics,
  checked first-class so a regeneration that drifts the ratio fails with a
  specific message even if the predicate itself changes).

The gate validates what the engine WILL load rather than re-fitting (a full
`calibrate-egarch` run takes minutes per symbol), so a regenerated fit that
lands in a degenerate basin — the measured full-corpus R_100 case — fails
the loop loudly the moment it lands on disk.  The row renders as
`CalibrationGate - PASS|FAIL`; add `-SkipCalibrationGate` to opt out.  Both
branches verified end-to-end on 2026-08-16: PASS on the healthy JSONs
(R_75 vol_ratio 0.607, R_100 0.814) and FAIL when R_75's vol_ratio was
corrupted to 0.00004 (exit 1, "1 suite(s) NOT green").

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

Demo account `5098680` on `DerivSVG-Server-03` returns
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

**Live-path & band-path exposure verified + frozen-vs-live A/B
(2026-08-12):** the freeze covered EVERY consumer of the assembler's
`build_snapshot` — the live dashboard read calls it directly AND
`DecisionEngine.evaluate` calls it again internally, so every live call's
confidence components (`_confidence_score` vol-ratio/|z| branches,
`_garch_mr_component`, `_vol_regime_component`) and the ML model's feature
vector saw z=0.0 / mr=0.0 / constant σ=0.02 / and — once the calibrated
priors landed — a pathological constant `garch_vol_ratio` ≈20 (→ the
"vol expansion" −0.10 confidence penalty on EVERY call).  The band path's
stop/target LEVELS were never frozen: `_structure_band_levels` derives them
from the strategy's own `_prev_sigma` (`band_levels(sigma_per_bar=…)`),
not the assembler garch — but the band/vol-dynamics confidence that gates
them (`_score_direction`) consumed the same frozen features.  The vol-band
BACKTEST leg is untouched (own per-bar `EGARCHVarianceForecaster`).
Frozen-vs-live A/B on the current 12.9-day corpus (frozen = old guard
emulated — `update()` never advances state; fresh model per run; same UTC
entry gate):

| run | n | hit | gross | net@0.05 | z_mean | \|z\|>1.5 | vr_mean | σ range |
|---|---|---|---|---|---|---|---|---|
| FROZEN | 159 | 50.9% | +0.192R | +0.142R | 0.00 | 0.0% | 19.85 | 0.0200 const |
| LIVE | 155 | 51.0% | +0.187R | +0.137R | −0.08 | 3.9% | 0.25 | 0.0016–0.0131 |

Call-level verdict: small — −4 trades (−2.5%), hit +0.0pp, gross
−0.004R.  The feature went from dead/constant to live, but the entry gate
(garch-independent |range_z_50|) plus the online model's adaptation absorb
almost all of the difference; the 4-trade delta is borderline-confidence
crossings from the systematic frozen penalty vs the live compression
boost.  The freeze's real cost was feature-vector health and the
systematic confidence bias in ungated regimes, not the gated leg's count.
Caveat: the live read feeds `build_snapshot` twice per read (panel +
evaluate) — the same last-bar log-return reaches the forecaster twice, a
minor recent-return overweight, not a freeze.

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

**Why ADWIN never fires — and the error-based detector is dead too
(2026-08-12, `_probe_adwin_why.py`, 12.9-day / 2,356-bar corpus):** the
return stream ADWIN (`|log_return|×100`, delta 0.002 — what the band/reversion
drift gates feed) fired **0 / 2,356** bars, and the model's error-stream ADWIN
(`abs(label−p)` per taken-trade update) fired **0 / 155** updates — the
`_drift_confidence_penalty` / `_dynamic_min_confidence` paths and both
strategies' drift-cooldown gates are inert on this corpus.  Two measured
reasons for the return stream: (1) **heavy tails swamp the mean signal** —
|r|% mean 0.194 / std 0.254 / p99 0.644 (3.3× the mean), while the actual
regime signal is only a rolling-250-bar mean swing of 0.169→0.291 (~0.12,
a ~1.7× vol change on R_75 M5); (2) **ADWIN's detectability floor at the
windows it can resolve** — eps(m=10)≈1.47 (a 7.5× instantaneous vol jump
would be needed), and even at m=100 the observed adjacent-half shift (0.173)
sits at 0.71× the floor; at m=250 a simplified offline floor is crossed
(ratio 1.39) but the real detector's window-spanning variance keeps it below
line — a gentle ramp shift in a heavy-tailed absolute-return stream is
structurally the wrong input for a mean-shift detector.  The error stream is
worse: starved to ~12 updates/day (UTC 12-24h trades only, so it never sees
regime changes outside the window) and its per-trade outcome noise
(mean 0.516, std 0.415, max 0.92) dwarfs any slow model-quality drift — a win
or a loss both produce a large |error| in every regime.  Verdict: neither
ADWIN variant is a usable entry-timing signal on this corpus; entry timing
is carried by the vol-extension gate + the UTC/|range_z| filter, as the sweep
above measured.  (Sanity: the detector does fire on real steps — the unit
tests feed 0.5→5.0; the R_75 regime moves are ~20× smaller.)
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
trades (~14/day), +0.111R net@0.05, +0.061R net@0.10, KEPT 146/146**.  The6-month combined measurement still requires porting the sniper ML path to
the tester (Python corpus is ~10.5 days).

**svcap OUT-OF-SAMPLE re-check (13.02-day corpus, 2026-08-12):** the
combined-gate probe re-run on the fresh ~2.5 days of corpus growth
(`mql5/svcap_recheck.py`, same methodology: real `run_ticks` passes,
TIME-exit broker, in-loop filtering, fresh model per run):

| cell | n | hit | gross | net@0.05 | net@0.10 | maxDD | streak | WF kept |
|---|---|---|---|---|---|---|---|---|
| sv (gate only) @13.02d | 150 | 50.7% | +0.190R | +0.140R | +0.090R | 5.71R | 5 | 149/150 |
| sv (10.5d ref) | 149 | 50.3% | +0.142R | +0.092R | +0.042R | 5.71R | 5 | — |
| **svcap @13.02d** | **147** | **52.4%** | **+0.210R** | **+0.160R** | **+0.110R** | **5.85R** | **5** | **147/147** |
| svcap (10.5d ref) | 146 | 52.1% | +0.161R | +0.111R | +0.061R | 5.85R | 5 | — |

**The +0.111R net@0.05 lift HOLDS out-of-sample — and improves to
+0.160R net@0.05** (+0.049R better than ref; hit 52.1 → 52.4%; the
2.5 days of fresh data were *better* than the training window, not
worse).  The depth-cap delta is stable too: svcap − sv = +0.020R
net@0.05 now vs +0.019R at 10.5d.  maxDD (5.85R), worst streak (5) and
walk-forward behavior (KEPT 147/147, no suppression) all reproduce.
First gate cell to survive a corpus-growth re-run without decay.


**Entry gate wired into the LIVE emission path (2026-08-11) — measured
end-to-end, not by a probe hook:** `SymbolProfile.entry_gate_*`
(enabled, UTC [12,24), |range_z_50| < 1.0) is now enforced INSIDE
`DecisionEngine.evaluate` for sniper mode — placed after the stateful
monitors (regime/calibration/GARCH stay fed every bar) and before
scoring, so out-of-window bars stand aside without freezing market
state or wasting model work.  Because `market_snapshot` resolves
sniper-only and the harness replica calls the same evaluate, the gate
now governs the live dashboard calls, the watch loop, and the
real-corpus harness alike.  Re-run of the harness (337 checks, 0
failed):

| leg | n | hit | gross | net@0.05 | net@0.10 | maxDD | WF gate |
|---|---|---|---|---|---|---|---|
| gated production broker (fixed 1.9R target) | 155 | 51.0% | +0.187R | +0.137R | +0.087R | — | KEPT |
| **gated time-exit (adopted research exit)** | **150** | **50.7%** | **+0.190R** | **+0.140R** | **+0.090R** | **5.71R** | KEPT 149/150 |

**The gate alone (no time exit) already flips the production sniper leg
positive** — 155 trades, 51.0% hit vs the 39.5% Stage-3 floor, +0.187R
vs the ungated +0.008R — and the gated time-exit leg reproduces the
probe's +0.14R net@0.05 at the live-path level (+0.190R gross, maxDD
5.71R, KEPT 149/150).  This is the first time the gate has been measured
with the online ML model, risk engine and broker all seeing it — the
probes filtered post-risk; the live path gates at emission, which the
end-to-end run shows is slightly BETTER (model never even scores
extreme-vol entries).  Test fixtures that synthesize candles at epoch
0 were re-anchored to a 13:00 UTC base so the gate doesn't stand
existing evaluate-based tests aside; new gate tests lock the behavior
(out-of-window → None + "entry gate" rationale; disabled → restored).

**Time-exit horizon sweep (2026-08-12, `_probe_time_exit_sweep.py`, 12.9-day
corpus):** the exit horizon was swept from 4h down to 1h (2h = the adopted
"mean positive-drift" baseline; same 1R band stop, target ignored, same UTC
gate, fresh online model per run, single-position broker so n grows as the
horizon shrinks):

| h | n | hit | gross | net@0.05 | net@0.10 | tot@0.05 | tot@0.10 | maxDD |
|---|---|---|---|---|---|---|---|---|
| 4.0h | 46 | 37.0% | **+0.541R** | +0.491 | +0.441 | +22.6 | +20.3 | 6.0R |
| **3.0h** | **55** | 38.2% | +0.491R | +0.441 | +0.391 | **+24.3** | **+21.5** | 8.3R |
| 2.0h (baseline) | 75 | 40.0% | +0.276R | +0.226 | +0.176 | +17.0 | +13.2 | 8.7R |
| 1.5h | 88 | 45.5% | +0.257R | +0.207 | +0.157 | +18.2 | +13.8 | 7.9R |
| 1.0h | 119 | 49.6% | +0.237R | +0.187 | +0.137 | +22.3 | +16.4 | **5.1R** |

Per-trade gross rises monotonically with horizon (still rising at 4h — the
per-trade peak sits beyond the sweep) while hit falls (49.6% → 37.0%): the
longer hold lets early winners mean-revert back while the trending winners
accumulate.  Costs do NOT change the per-trade ordering (4h is best at any
cost) but DO change the total-return optimum: the n-collapse (46 vs 119
trades) moves the total-net peak to **3h** (+24.3R @0.05 / +21.5R @0.10),
with 1h the runner-up at 0.05 cost (+22.3R, best drawdown 5.1R, best hit
49.6%).  The adopted 2h baseline is the WORST cell on total net (+17.0R) —
a local minimum of the sweep.

**UTC 12-24h filtered-cell re-check @ 12.9 corpus days (2026-08-12):**
`mql5/utc_cell_recheck.py` (durable — re-run as the corpus grows)
replays the captured sniper leg and splits it by the sweep cells; corpus
is 12.92 days / 172,368 ticks (not yet 15 — checkpoint measurement),
and the replay matches realized exactly (51.0% == 51.0%, n=155).  The
live gate is the production default now, so the entire capture sits in
the 12-24h cell (cell == baseline); the strict subset is 18-24h:

| cell | n | hit@1.2 | exp@1.2 | hit@1.5 | exp@1.5 | medMFE |
|---|---|---|---|---|---|---|
| UTC 12-24h & |range_z|<1.0 (was n=34 / 58.8% / +0.246R) | 155 | 54.2% | +0.175R | 51.6% | +0.199R | +0.98R |
| **UTC 18-24h & |range_z|<1.5 (was n=24 / 58.8% / +0.267R)** | **67** | **58.2%** | **+0.242R** | **55.2%** | **+0.304R** | **+1.12R** |

**The edge survives n-growth; the narrow session window is the robust
form.**  The 12-24h cell diluted toward n=155 (58.8% → 54.2% hit,
+0.246R → +0.175R exp — positive, above the RR-1.2 floor, but weaker),
while the 18-24h & |range_z|<1.5 cell held almost exactly at n=67 ≥ 60
(hit 58.2%, exp +0.242R@1.2 / +0.304R@1.5, medMFE +1.12R).  Re-run
`utc_cell_recheck.py` once the corpus passes ~15 days for the final
confirmation.

**Deep-vs-shallow + vol-regime profile on the sniper leg (2026-08-12,
12.99-day corpus, 155 gated trades, fidelity replay MATCH 51.0%) —
`utc_cell_recheck.py` now records per-trade entry features and splits the
realized production geometry (fixed 1.9R target / 1R stop):**

| depth (\|range_z_50\|) | n | hit | exp | sumR | maxDD | medMFE |
|---|---|---|---|---|---|---|
| rz<0.33 (near-center) | 44 | 47.7% | +0.251R | +11.0R | 7.3R | +0.87R |
| rz 0.33-0.66 | 51 | 45.1% | +0.086R | +4.4R | 8.4R | +0.95R |
| **rz>=0.66 (band-edge)** | **60** | **58.3%** | **+0.227R** | **+13.6R** | **2.9R** | **+1.10R** |

| vol-regime (garch_vol_ratio) | n | hit | exp | sumR | maxDD | medMFE |
|---|---|---|---|---|---|---|
| **vol<=1.25** | **138** | **52.2%** | **+0.220R** | **+30.3R** | **5.7R** | **+1.02R** |
| vol>1.25 | 17 | 41.2% | −0.076R | −1.3R | 4.0R | +0.91R |

**The sniper edge CONCENTRATES — the opposite of the band's flat
profile.**  The MQL5 band holds identical hit/MFE across depth (bleeding
by volume); the sniper's edge is NOT flat: the **band-edge entries
(rz>=0.66) are the strongest cell** — 58.3% hit, +0.227R, the LOWEST
maxDD (2.9R) and highest medMFE (+1.10R) — while the mid-depth cell is
the weak pocket (45.1%, +0.086R).  And the edge lives in **normal vol**
(vol<=1.25: 52.2%, +0.220R, +30.3R sumR over 138 trades); the
extreme-vol minority (17 trades, 11%) is the only negative pocket
(41.2%, −0.076R).  Two discardable pockets identified: mid-depth and
vol>1.25.  Caveats: single 12.99-day window, n=155 total (vol>1.25 n=17),
and this band-edge axis (\|range_z_50\| within the <1.0 gate) is
consistent with — not contradictory to — the older \|garch_z\|≥1.0
finding, which measured stretched log-return z on the UNGATED book.

**Direction + hour split of the forward-pass cell (2026-08-12, 13.01-day
corpus, UTC 18-24h & |range_z|<1.5, n=67, fidelity MATCH) — does the edge
concentrate further or is it balanced?**  `utc_cell_recheck.py` now
splits the cell by side and hour (replay at RR 1.2/1.5; realized =
production 1.9R geometry):

| side | n | hit@1.2 | exp@1.2 | hit@1.5 | exp@1.5 | realized(1.9R) | medMFE |
|---|---|---|---|---|---|---|---|
| LONG | 52 | 59.6% | +0.264R | 55.8% | +0.303R | 53.8%/+0.310R | +1.13R |
| SHORT | 15 | 53.3% | +0.166R | 53.3% | +0.306R | 53.3%/+0.175R | +1.12R |
| ALL | 67 | 58.2% | +0.242R | 55.2% | +0.304R | 53.7%/+0.279R | +1.12R |

| hour | n | hit@1.2 | exp@1.2 | realized(1.9R) | medMFE |
|---|---|---|---|---|---|
| 18-19 | 9 | 66.7% | +0.226R | 66.7%/+0.229R | +1.08R |
| 19-20 | 9 | 88.9% | +0.956R | 77.8%/+0.894R | +1.40R |
| 20-21 | 13 | 46.2% | +0.096R | 46.2%/+0.307R | +0.67R |
| 21-22 | 14 | 57.1% | +0.133R | 57.1%/+0.256R | +0.73R |
| 22-23 | 9 | 44.4% | +0.146R | 33.3%/−0.036R | +0.84R |
| 23-24 | 13 | 53.8% | +0.089R | 46.2%/+0.106R | +1.10R |
| **18-21 coarse** | **31** | **64.5%** | **+0.383R** | **61.3%/+0.455R** | **+1.28R** |
| 21-24 coarse | 36 | 52.8% | +0.120R | 47.2%/+0.129R | +0.84R |

**Verdict: the edge is balanced across direction but concentrates by
hour.**  Both sides are positive (LONG 59.6%/+0.264R with 78% of the
volume; SHORT 53.3%/+0.166R) and they converge at RR 1.5 (+0.303 vs
+0.306) — no one-sided dependency, the ML scoring simply favors longs in
this window.  The hour split is the concentrated axis: the FIRST half of
the window (18-21) carries nearly all the strength — 64.5% hit,
+0.383R@1.2, realized +0.455R@1.9 — vs the back half's 52.8%/+0.120R;
19-20 is the standout hour (88.9%, +0.956R) and 22-23 is the only
sub-50% cell (44.4%, realized −0.036R).  Caveats: hourly cells are thin
(n=9-14; the coarse 18-21/21-24 split of 31/36 is the firmer read), and
this is the same single 13-day window.  The RUNNING forward pass stays
on 18-24 (changing it mid-pass would invalidate the out-of-sample test);
the 18-21 concentration is the refinement candidate for the NEXT pass.

**rz-tightening ladder (UTC 12-24h gate, 13.02-day corpus, 2026-08-12):**
the user hypothesis — a tighter vol gate (rz<0.7) lifts hit/net at the
cost of trade count — is **disproven**: tightening DILUTES the edge.  On
the 155-trade gated population (fidelity MATCH), moving the |range_z_50|
cap 1.0 → 0.7 lowers hit 54.2 → 50.0%, expectancy +0.175 → +0.110R and
net@0.05 +0.125 → +0.060R while cutting trade count 34% (155 → 102);
the 0.6 step bounces to +0.145R on noise (n=85).  The reason is the
inverse of the band: on the sniper, the BAND-EDGE entries (rz 0.7-1.0,
which the tighter cap deletes) are the strongest cell — the deep-vs-
shallow profile's rz>=0.66 bucket is 58.3% hit / +0.227R / 2.9R maxDD —
so removing them removes the edge.  The hour axis dominates: 18-24 &
rz<0.7 (n=48) still runs 56.2%/+0.186R because 18-21 is the strong half
of the window.  Conclusion: keep |range_z|<1.0; the band-edge entries
are the edge, not a tail to trim.

| cell | n | hit@1.2 | exp@1.2 | net@0.05 | hit@1.5 | exp@1.5 | medMFE |
|---|---|---|---|---|---|---|---|
| UTC 12-24h & rz<1.0 (gate) | 155 | 54.2% | +0.175R | +0.125R | 51.6% | +0.199R | +0.98R |
| UTC 12-24h & rz<0.8 | 118 | 51.7% | +0.141R | +0.091R | 49.2% | +0.180R | +0.95R |
| UTC 12-24h & rz<0.7 | 102 | 50.0% | +0.110R | +0.060R | 47.1% | +0.150R | +0.93R |
| UTC 12-24h & rz<0.6 | 85 | 51.8% | +0.145R | +0.095R | 48.2% | +0.184R | +0.93R |
| UTC 18-24h & rz<0.7 | 48 | 56.2% | +0.186R | +0.136R | 52.1% | +0.235R | +1.08R |
| UTC 18-24h & rz<1.5 (fwd pass) | 67 | 58.2% | +0.242R | +0.192R | 55.2% | +0.304R | +1.12R |

**12-24h hour ladder — the edge concentrates in THREE hours, not one block
(13.02-day corpus, 2026-08-12):** per-hour replay of the gated population
(155 trades, fidelity MATCH):

| hour | n | hit@1.2 | exp@1.2 | net@0.05 | trades/day |
|---|---|---|---|---|---|
| 12-13 | 17 | 64.7% | +0.390R | +0.340R | 1.3 |
| 13-14 | 12 | 50.0% | +0.034R | −0.016R | 0.9 |
| 14-15 | 19 | 42.1% | −0.035R | −0.085R | 1.5 |
| 15-16 | 15 | 46.7% | +0.055R | +0.005R | 1.2 |
| 16-17 | 15 | 60.0% | +0.289R | +0.239R | 1.2 |
| 17-18 | 10 | 40.0% | −0.064R | −0.114R | 0.8 |
| 18-19 | 9 | 66.7% | +0.226R | +0.176R | 0.7 |
| 19-20 | 9 | 88.9% | +0.956R | +0.906R | 0.7 |
| 20-21 | 13 | 46.2% | +0.096R | +0.046R | 1.0 |
| 21-22 | 14 | 57.1% | +0.133R | +0.083R | 1.1 |
| 22-23 | 9 | 44.4% | +0.146R | +0.096R | 0.7 |
| 23-24 | 13 | 53.8% | +0.089R | +0.039R | 1.0 |

Best contiguous sub-windows: **4h 16-20 → 62.8%/+0.333R/net +0.283R
(3.3/day, n=43)**; 5h 18-23 → 59.3%/+0.279R (4.1/day); 6h 16-22 →
58.6%/+0.249R (5.4/day) vs the full 12-24h gate's 54.2%/+0.175R/net
+0.125R (11.9/day).  Three strength pockets: 12-13 (n=17, 64.7%, +0.390R),
16-17 (60.0%, +0.289R) and 19-20 (n=9, 88.9%, +0.956R — thin); two
net-negative hours drag the window: 14-15 (−0.035R) and 17-18 (−0.064R).
So a tighter sub-window DOES roughly double expectancy at 28-45% of the
trade count — the 18-23h / 16-22h candidates (4-5/day) are the balance
point.  Caveats: hourly cells are thin (n=9-19) and the window was
chosen on this single 13-day corpus — the candidates need an out-of-
sample re-check before replacing the running 18-24h pass (which sits at
+0.242R, statistically indistinguishable from 16-22's +0.249R).

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

**Per-bucket drawdown attribution via equity-curve position
(2026-08-12, RR 3.0 default geometry):** `BandBackTests` now records each
trade's equity-curve position at close, so max drawdown is computed per
depth bucket directly from reconstructed per-bucket equity curves (no
sumR proxy):

| bucket | n | hit | exp | sumR | maxDD | maxDD/trade |
|---|---|---|---|---|---|---|
| shallow ≤1.5 | 171 | 26.3% | +0.053R | +9.0R | 22.0R | 0.129R |
| mid 1.5-2.5 | 326 | 25.8% | +0.031R | +10.0R | 37.0R | 0.114R |
| deep >2.5 | 1,040 | 25.1% | +0.005R | +5.0R | 59.0R | 0.057R |

**Direct measurement refines the "bleed by volume" story:** the deep
fades own the largest ABSOLUTE drawdown (59.0R — 68% of the book), but
the SMALLEST per-trade drawdown (0.057R/trade vs shallow 0.129R, mid
0.114R).  The earlier depth-cap "6× drawdown cut" was therefore
mechanical count-scaling after all — removing 1,040 trades' worth of DD
accumulation, not a tail.  The shallow fades are the sharper per-trade
risk AND the better expectancy (+0.053R); the deep bucket is the
lowest-risk-per-trade leg that simply never converts (hit 25.1% vs 30%
floor).  The equity-position field now ships in every BandBackTests
report.

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

**Closed-candle trail grace — the trail STOPPED racing the target
(same window, 2026-08-11):** the escape hatch above is now implemented
(`InpTrailClosedCandle=true`): once armed (eff_stop == entry) the
breakeven exit only fires when an M5 candle CLOSES through entry — a wick
can no longer scratch a runner (mirrors the Python stop-lock).  Re-swept
InpTrailFrac 0.2–0.8 at RR 1.2 with the grace ON:

| frac | arm | n | hit | exp gross | exp@0.05 | maxDD |
|---|---|---|---|---|---|---|
| 0.0 | off | 1,796 | 40.4% | −0.112R | −0.162R | 204.8R |
| **0.2** | 0.24R | **1,818** | **43.6%** | **+0.398R** | **+0.348R** | **5.8R** |
| 0.4 | 0.48R | 1,800 | 43.5% | +0.283R | +0.233R | 7.8R |
| 0.5 | 0.60R | 1,809 | 44.2% | +0.241R | +0.191R | 12.4R |
| 0.6 | 0.72R | 1,778 | 43.9% | +0.199R | +0.149R | 13.2R |
| 0.7 | 0.84R | 1,811 | 43.9% | +0.152R | +0.102R | 17.0R |
| 0.8 | 0.96R | 1,831 | 43.5% | +0.117R | +0.067R | 21.4R |

**Complete turnaround: every frac is positive, hit holds at 43.5–44.2%
(vs 2–4% without the grace), and drawdown collapses 204.8R → 5.8R at
frac 0.2.**  The wick-scratch was the entire problem — not late arming.
With the grace, winners survive their pullbacks and the trail converts
would-be −1R losers to 0R breakevens (~44% of trades scratch at entry;
the real loss rate falls to ~12%).  Best cell: **frac 0.2 — +0.398R gross,
+0.348R net@0.05, +0.298R net@0.10, maxDD 5.8R** — the first positive-net
band geometry at ANY RR, reproduced on the next-day window (+0.390R
/+0.340R).  The honesty note: this rests on the closed-candle fill model
the user chose (a wick through the breakeven level does NOT fill); with
wick fills it is the old 2%-hit disaster.  Default stays 0.0 — flipping
is a one-flag decision (`InpTrailFrac=0.2;InpTrailClosedCandle=true`)
after the fresh-window confirmation.

**RR-3.0 trail sweep with the grace (default geometry, same window,
2026-08-11):** does the trail behave the same when the target is 3.0R
instead of 1.2R?  Same qualitative shape — every frac positive, hit
holds (no collapse), drawdown crushed — and the optimum moves EARLIER:

| frac | arm (x3R) | n | hit | exp gross | exp@0.05 | exp@0.10 | maxDD |
|---|---|---|---|---|---|---|---|
| 0.0 | off | 1,537 | 25.4% | +0.016R | −0.034R | −0.084R | 81.0R |
| **0.1** | **0.30R** | **1,537** | **28.1%** | **+0.687R** | **+0.637R** | **+0.587R** | **7.0R** |
| 0.2 | 0.60R | 1,526 | 29.0% | +0.582R | +0.532R | +0.482R | 13.0R |
| 0.4 | 1.20R | 1,526 | 28.4% | +0.380R | +0.330R | +0.280R | 18.0R |
| 0.5 | 1.50R | 1,511 | 27.5% | +0.273R | +0.223R | +0.173R | 33.0R |
| 0.6 | 1.80R | 1,506 | 27.7% | +0.233R | +0.183R | +0.133R | 32.0R |
| 0.7 | 2.10R | 1,495 | 27.7% | +0.194R | +0.144R | +0.094R | 36.0R |
| 0.8 | 2.40R | 1,529 | 27.3% | +0.156R | +0.106R | +0.056R | 47.0R |

**frac 0.1 (arm at 0.30R) is the strongest band configuration ever
measured: +0.687R gross, +0.637R net@0.05, +0.587R net@0.10, maxDD 81R
→ 7R, hit 28.1%.**  The RR-3.0 win/loss/scratch mix at 0.1: 28.1% win
+3R, ~56% scratch 0R, only ~16% lose −1R (84% of trades never lose).
STRONG (deep) bucket carries it (+0.697R, n=1469) — consistent with the
RR-3.0 depth profile where deep fades are the positive buckets.  **One
measurement-lens caveat that matters now:** with breakeven exits, the
Stage-3 hit-vs-floor test (28.1% vs 30.0% floor) counts 0R scratches as
losses and is no longer the right gate — the realized payout BE (wins
+3R, losers −1R, 56% scratches) is far below 28.1%.  The floor logic
should treat 0R outcomes as non-losses before this geometry is judged
floor-beatable.

**Arming-to-exit path instrumentation (2026-08-11) — how many trades the
grace actually saves:** `BandBackTests` now records per trade the bar the
trail armed at, the arm MFE, and the count of post-arm bars that wick
through entry.  Counterfactual: any armed trade with ≥ 1 wick-through
would have been scratched at 0R by the old same-candle rule; the ones
that STILL reached target are the trades the closed-candle grace
converts from a 0R scratch to a +RR win.  Measured on the two RR-3.0
cells:

| frac | armed | wick-through | saved (0R→target) | saved R | grace R/trade |
|---|---|---|---|---|---|
| 0.1 | 1,299/1,537 (84.5%) | 449 (34.6%) | **125** | **+375R** | **+0.244R** |
| 0.8 | 514/1,529 (33.6%) | 92 (17.9%) | 19 | +57R | +0.037R |

**The mechanism, now quantified:** early arming (frac 0.1, arm at 0.30R)
arms 84.5% of trades — most positions touch 0.30R MFE — and 34.6% of
them then wick back through entry at least once, the exact jitter the
grace spares.  Of those 449 wick-throughs, 125 (28%) went on to hit the
3.0R target — **+375R the old rule would have thrown away, +0.244R over
every trade in the run**.  Late arming (frac 0.8, arm at 2.40R) arms only
33.6% (few trades ever reach 2.4R MFE), and its wick-through rate is
half (17.9%) because a trade that reached 2.4R usually runs straight to
3.0R — so it saves only 19 trades (+0.037R/trade).  This is the
quantitative reason the optimum sits at the earliest arm: the grace
converts the most scratches exactly where the trail arms earliest, while
the breakeven-exit group (867 at frac 0.1) is 0R either way.  (Per-trade
arm_hold/arm_mfe/dips fields now land in the journal record for every
trade.)

**Trail × edge-depth cross-tab (2026-08-11) — do shallow fades survive
the trail better than deep extensions?**  The arming-path stats are now
split by the same depth buckets (|z|/z_entry: shallow ≤1.5, mid
1.5-2.5, deep >2.5):

*frac 0.1 (arm 0.30R, the adopted cell):*

| bucket | n | hit | exp | armed% | wick-thru% | saved/conv | saved R/trade |
|---|---|---|---|---|---|---|---|
| shallow ≤1.5 | 160 | 23.8% | +0.531R | 81.9% | 38.2% | 14/50 (28.0%) | +0.262R |
| **mid 1.5-2.5** | **346** | **32.4%** | **+0.812R** | 84.1% | 34.0% | 36/99 (**36.4%**) | **+0.312R** |
| deep >2.5 | 1,031 | 27.4% | +0.670R | 85.1% | 34.2% | 75/300 (25.0%) | +0.218R |

*frac 0.4 (arm 1.20R):*

| bucket | n | hit | exp | armed% | wick-thru% | saved/conv | saved R/trade |
|---|---|---|---|---|---|---|---|
| shallow ≤1.5 | 153 | 26.1% | +0.301R | 51.6% | **45.6%** | 11/36 (**30.6%**) | **+0.216R** |
| mid 1.5-2.5 | 341 | 27.6% | +0.355R | 52.8% | 42.8% | 18/77 (23.4%) | +0.158R |
| deep >2.5 | 1,032 | 29.1% | +0.400R | 52.9% | 37.2% | 52/203 (25.6%) | +0.151R |

**Verdict: NO — at the adopted frac 0.1 the shallow fades are the
WEAKEST bucket under the trail, not the strongest.**  Mid depth carries
the edge (hit 32.4%, exp +0.812R, the best wick-through conversion
36.4%, and the most saved R per bucket trade +0.312R); shallow is
bottom on exp (+0.531R) and conversion (28.0%), deep sits in between.
The shallow fades arm just as eagerly (81.9%) but their marginal entries
convert to breakeven instead of running: the bucket's BE-trail exit rate
is the highest (58.1%) and its hit rate actually DROPS vs the no-trail
measurement (28.0% → 23.8%, the scratches now counting as losses),
though expectancy still turns strongly positive (+0.119R → +0.531R) as
the losers become 0R scratches.  Ordering flips at the later arm (frac
0.4: shallow converts best, 30.6%), but all three buckets are positive
at every frac — the trail+grace helps every depth class, just most of
all the mid-depth fades.

**RR 2.5-3.5 finer map (2026-08-12, `-Inputs
InpDerivedTargetRR=<rr>;InpMinTargetRR=<rr>`, 0.25 steps, fresh 6-month
window):** the coarse §50 grid found the hit-vs-floor gap narrowing to a
~−4-point minimum around RR 3.0; the 0.25-step map pins it exactly:

| RR | n | hit | exp gross | floor | gap (hit−floor) | tot net@0.05 |
|---|---|---|---|---|---|---|
| 2.50 | 1,649 | 27.6% | −0.034R | 33.6% | −6.0 | −138.5R |
| 2.75 | 1,572 | 26.9% | +0.009R | 31.7% | −4.8 | −64.5R |
| **3.00** | **1,537** | **25.4%** | **+0.016R** | **30.0%** | **−4.6** | **−52.3R** |
| 3.25 | 1,483 | 23.8% | −0.040R | 28.5% | −4.7 | −133.5R |
| 3.50 | 1,455 | 21.9% | −0.137R | 27.2% | −5.3 | −272.1R |

**RR 3.0 is the exact optimum of the zone** — the gap minimum (−4.6pp)
and the best expectancy (+0.016R; both 0.25 neighbors already lose it,
3.5 collapses to −0.137R on the MFE cliff).  Trade count falls
monotonically with RR (slot-occupancy), and the ≤1.25 shallow bucket
clears its floor (31.4% vs 30.0%) while the full population still misses
by 4.6pp — the Stage-3 gate keeps standing the band leg aside at every RR
in the zone.

**Wider-stop test at RR 1.2 (2026-08-12, 6-month window, sweep OFF,
`InpGeomSweep=false;InpStopSigmaMult=<s>;InpTargetSigmaMult=<1.2s>`,
`InpDerivedTargetRR=1.2;InpMinTargetRR=1.2`):** hypothesis — a wider
stop cuts the ~59% stop-out rate enough to lift hit toward the 50.5%
floor:

| cell | stop/target σ | n | hit | exp gross | stop-out | floor gap |
|---|---|---|---|---|---|---|
| base RR 1.2 (sweep ON, 0.15-0.35σ) | ~0.2σ | 1,932 | 39.4% | −0.132R | 60.6% | −11.1 |
| stop 0.50 / target 0.60 | 0.50/0.60 | 1,719 | 45.2% | −0.006R | 54.8% | −5.3 |
| stop 0.60 / target 0.72 | 0.60/0.72 | 1,585 | 44.7% | −0.016R | 54.9% | −5.8 |
| stop 0.70 / target 0.84 | 0.70/0.84 | 1,501 | 45.0% | −0.015R | 53.9% | −5.5 |

**Directionally confirmed but insufficient alone:** the stop-out rate
drops 60.6% → ~54% and hit jumps 39.4% → ~45% — but hit PLATEAUS at
~45%, still −5.5pp short of the 50.5% floor, and expectancy lands at raw
breakeven (−0.006R at 45.2% vs the 45.45% no-margin breakeven).  Wider
stops also cost trade count (1,932 → 1,501 — wide stops trip
`InpMaxStopPct=1.5%` more often).  **The hidden winner: the MID-depth
bucket (depth 1.5-2.5) flips from the worst (37.9%, −0.166R at baseline)
to floor-beatable with wide stops — 49.6%/+0.091R (0.50σ), 50.8%/+0.119R
(0.60σ — CLEARS the 50.5% floor), 49.8%/+0.102R (0.70σ).**  A
width-depth-window combo (depth 1.5-2.5 × 0.60σ stop) is the next
candidate, not the full book.

**Session-hour gate on the band (2026-08-12, 6-month window,
`InpSessionHourStart/End`, default 0/24 = OFF — the sniper's proven UTC
12-24h edge applied to the band):** the tester reports server→UTC
offset 0, so bar hours ARE UTC hours here (apples-to-apples with the
Python corpus's gmtime).

| geometry | gate | n | hit | exp gross | net@0.05 | floor gap |
|---|---|---|---|---|---|---|
| RR 3.0 (default) | none | 1,537 | 25.4% | +0.016R | −0.034R | −4.6 |
| **RR 3.0** | **UTC 12-24** | **846** | **26.6%** | **+0.063R** | **+0.013R** | **−3.4** |
| RR 1.2 | none | 1,932 | 39.4% | −0.132R | −0.182R | −11.1 |
| RR 1.2 | UTC 12-24 | 1,024 | 41.3% | −0.091R | −0.141R | −9.2 |

**The hour edge helps the band — most at RR 3.0, and it flips the
shallow subset floor-beatable.**  At RR 3.0 the gate cuts trade count
45% (1,537 → 846) and lifts expectancy 4× (+0.016 → **+0.063R**),
turning net@0.05 positive (+0.013R) — the first positive-cost cell on
the default geometry.  The depth-split cells now CLEAR their floors:
depth ≤1.25 → hit 40.0% vs 30.0% floor (exp **+0.600R**, n=35); ≤1.50 →
30.9%/+0.235R; ≤2.00 → 30.3%/+0.212R; ≤2.50 → 30.2%/+0.207R — only the
full population (26.6%) still misses by 3.4pp.  This revises the
earlier "depth-cap HURTS at RR 3.0" claim: cap + session hour together
DO clear the floor.  At RR 1.2 the gate lifts hit 39.4 → 41.3% but the
−9.2pp floor gap remains (expectancy still negative).  Caveat: single
6-month window; the gate removed mostly deep (>2.5) entries — the same
bucket the wide-stop test flagged as the drag.

**Time-exit + UTC-entry filter ported end-to-end (2026-08-12, 6-month
window) — does the Python harness's +0.14R edge hold on the MQL5 band
leg?**  `InpExitMode=1` (TIME) + `InpSessionHourStart/End` + the NEW
`InpMaxRangeZ` filter (|range_z_50| — z of the current M5 range vs the
prior-50 range window, population std, faithful to indicators.py
zscore; 0 = OFF):

| config (band, RR 3.0 unless noted) | n | hit | exp gross | net@0.05 | CI |
|---|---|---|---|---|---|
| TIME@1h alone (no filters) | 1,355 | 15.1% | +0.125R | +0.075R | PASS |
| **TIME + UTC 12-24 + rz<1.0** | **574** | **13.1%** | **+0.094R** | **+0.044R** | PASS |
| TIME + UTC 12-24 (no rz) | 756 | 13.0% | −0.013R | −0.063R | PASS |
| TIME + UTC 18-24 + rz<1.5 | 350 | 12.3% | −0.127R | −0.177R | FAIL (shallow 0%) |
| TIME + 12-24 + rz<1.0 @ RR 1.2 | 615 | 12.7% | −0.050R | −0.100R | FAIL (shallow −0.71R) |

**Python reference (sniper leg, same combo): n=149, hit 50.3%, +0.142R
gross / +0.092R net@0.05.**

**Verdict: the direction and the rz mechanism replicate, the magnitude
does not.**  The |range_z|<1.0 filter's contribution REPRODUCES exactly
the Python pattern — it flips the session-filtered TIME leg from
−0.063R to +0.044R net@0.05 (+0.107R/trade), confirming the port's
fidelity.  But the full +0.14R edge does NOT transfer: the ported combo
lands at +0.044R net@0.05 — roughly half the Python's +0.092R — and is
WORSE than the band's own unfiltered TIME@1h (+0.075R net@0.05,
+101.6R total vs +25.3R total; the session+rz filters cut trade count
58% and diluted the band edge).  The Python edge is sniper-leg-specific
(ML-scored entries, ~50% hit at the 1h horizon); the band leg in TIME
mode is a different population (~13% hit, ~87% stop-outs) whose edge
lives in the DEEP bucket (cell A: deep exp +0.132R, sumR +49.7R — the
1h TIME exit converts the deep fades' +2.7-3.0R median MFE into
realized gains, the opposite of TARGET mode where deep is the drag).
RR 1.2 and the 18-24h window are both negative in TIME mode on the
band.  **Band's best stays TIME@1h, no entry filters.**

**Shallow-fade + TIME-exit test — does the shallow edge clear the 30%
floor?  NO (measured 2026-08-12, seed 42, RR 3.0):** the hypothesis was
that the shallow bucket's positive TARGET-mode expectancy (<=1.50:
n=171, hit 26.3%, +0.053R) would be lifted by the 1h TIME exit.  It is
not — TIME mode's hit metric is positive-R closes (~14-16% by design at
the 1h horizon), so the floor gate keying on a 3.0-RR planned geometry
(30% floor) gets further away, not closer:

| depth bucket | TARGET n/hit/exp | TIME n/hit/exp |
|---|---|---|
| <=1.25 | 86 / 31.4% / +0.256R | 60 / 11.7% / +0.014R |
| **<=1.50** | **171 / 26.3% / +0.053R** | **115 / 13.9% / +0.062R** |
| <=2.00 | 329 / 25.8% / +0.033R | 257 / 15.6% / +0.127R |
| <=2.50 | 497 / 26.0% / +0.038R | 403 / 16.6% / +0.257R |
| <=3.00 | 693 / 25.4% / +0.017R | 549 / 16.2% / +0.229R |
| verdict | hit 25.4% does NOT beat 30% | hit 15.1% does NOT beat 30% |

Shallow <=1.50 hit CRASHES 26.3% -> 13.9% (floor gap widens -3.7pp ->
-16.1pp) while exp barely moves (+0.053R -> +0.062R).  The TIME edge at
RR 3.0 is the MIRROR of TARGET mode: expectancy rises monotonically
with depth (+0.014R at <=1.25 up to +0.229R at <=3.00) — the 1h exit
realizes the deep fades' large MFE, and the shallow fades (small MFE,
rarely positive at the horizon) are the weakest bucket.  And the 30%
floor is STRUCTURALLY un-beatable in TIME mode: hit ~14-16% needs a
~9R planned geometry for 1/(1+RR)+5% to drop to 15%, so no RR makes
the current TIME-mode hit clear its own floor.

**svcap ported to the tester as a forward-test candidate (6-month SYN75
window, 2026-08-12):** the sniper's full svcap configuration is now a
first-class tester config — `InpMaxGarchZ` (new input; |garch_z_score|,
the entry bar's log-return over the post-update conditional EGARCH sigma
— Python `arch_garch.update`'s `z_score = log_return / current_sigma`,
faithful including the current bar's own return) joins the already-ported
TIME exit, UTC 12-24h and |range_z|<1.0:

| config (all TIME exit) | n | hit | gross | net@0.05 | maxDD | CI |
|---|---|---|---|---|---|---|
| UTC 12-24 + rz<1.0 @ RR 3.0 (no gz) | 574 | 13.1% | +0.094R | +0.044R | — | PASS |
| **svcap (gz<=1.5) @ RR 3.0** | **450** | **13.3%** | **−0.082R** | **−0.132R** | **71.3R** | FAIL (shallow −0.455R) |
| UTC 12-24 + rz<1.0 @ RR 1.2 (no gz) | 615 | 12.7% | −0.050R | −0.100R | — | FAIL (shallow −0.71R) |
| **svcap (gz<=1.5) @ RR 1.2** | **478** | **13.8%** | **+0.054R** | **+0.004R** | **44.2R** | FAIL (shallow hit 0%) |

**The garch-z depth cap is geometry-dependent on the band leg — and the
sniper's svcap edge does NOT transfer.**  At RR 3.0 the cap HURTS: it
filters 5,035 candidate bars (diag gzskip) and removes exactly the
deep-extension entries the 1h TIME exit converts into gains (deep exp
flips +0.132R → −0.218R, sumR −63.8R), flipping the leg from +0.094R to
−0.082R gross.  At RR 1.2 the cap HELPS: mid-depth (1.5-2.5) concentrates
the edge — n=127, hit 18.1%, **+0.334R**, sumR +42.4R, maxDD 20.5R — and
the leg goes −0.050R → +0.054R gross (net@0.05 −0.100R → +0.004R,
breakeven), maxDD 44.2R vs the RR-3.0 cell's 71.3R.  Either way the band
leg in TIME mode stays a ~13-14% hit population vs the 50.5% (RR 1.2)
/ 30.0% (RR 3.0) floors, so the Stage-3 gate correctly stands aside at
both geometries; the mid-bucket +0.334R cell is the sharpest positive
subset measured on the band in TIME mode but is not itself gate-clean.
The Python svcap edge (52% hit, +0.160R net@0.05) remains sniper-leg-
specific — ML-scored entries on a different population — and this port
confirms the filters alone do not transplant it.

**Forward-demo paper pass (started 2026-08-12 ~02:50 UTC) — UTC 18-24h
& |range_z_50|<1.5 on the LIVE sniper leg, 30-trade target:**
`mql5/forward_demo_pass.py` runs `run_live_paper` (venue=MT5,
`Mt5TickClient` on the Deriv terminal — MT5-first, paper fills via
SimulatedExecutionBackend, NO orders ever sent) with the R_75
`SymbolProfile` entry gate overridden to UTC [18,24) & |range_z_50|<1.5
(the strongest measured cell: n=67/hit 58.2%/+0.242R@RR1.2 backtest,
+0.141R net@0.05 harness).  Journal:
`journals/forward_demo_18_24.jsonl` (every decision_skip/signal/
outcome); log: `.freebuff/forward_demo_18_24.log`.  The loop runs 3h
chunks with restart-on-crash, counting `type=outcome` records, and stops
at 30 closed trades (~6 days at the measured ~5/day); hard cap 7 days.

**Two live-path fixes this pass required (both now in the code):**
(1) `Mt5TickClient._connect` REUSES the running terminal's session when
no credentials are configured (`account_info` populated) instead of
crashing on `int(None)` — the terminal is the source of truth for what
it's connected to; credentialed behavior is byte-identical when
credentials ARE set.  Verified live: `reusing running terminal session
(5098680@DerivSVG-Server-03)`, init 2ms, no login round-trip.
(2) `run_live_paper` now passes the remaining run duration as the tick
stream timeout — `Mt5TickClient.subscribe_ticks`/Deriv default is a 20s
batch, so `duration_sec` chunks previously ended after one batch and the
candle warmup never accumulated past its seed (every evaluation skipped
"need 30 candles"); the stream now lives as long as the session.

**Status as of launch (UTC ~02:50):** one clean instance, first 3h
chunk, 30+ candles built, and the journal records the gate firing
correctly — `"entry gate: UTC hour 2 outside [18, 24) window"` — so no
trades until 18:00 UTC as configured.  Check progress with
`wc -l journals/forward_demo_18_24.jsonl` and `grep -c '"type":
"outcome"' journals/forward_demo_18_24.jsonl`.  Caveats: the Deriv
terminal must stay running/logged in (the pass reuses its session); each
chunk starts a fresh online model (matches the backtest's
fresh-model-per-run methodology); the single-flight guard serializes
terminal init against the scheduled collector.

**CLOCK-CONSISTENCY FIX (2026-08-12, found via the pass's own journal):**
the Deriv terminal stamps ticks in SERVER time, which runs exactly
+3h ahead of the local machine clock (measured: latest_tick time_msc −
time.time() = +10800.9s; the backfill corpus's last-row epoch read as
server time matches its file mtime to the second — the RESEARCH corpus
and its "UTC 18-24h" edge are server-time).  `Mt5TickClient.subscribe_ticks`
was stamping live ticks with `time.time()` (local) while `ticks_history`
warmup used `time_msc` (server) — so live candles landed 3h BEHIND the
warmup candles, the journal epochs went non-monotonic (a skip stamped
09:58 written at 09:16), the builder stalled on mixed-clock buckets
("need 30 candles, have 3" for hours), and the entry gate would have
fired 3h late vs the backtest.  Fix: `subscribe_ticks` now stamps
`time_msc` (fallback `time.time()` only when time_msc == 0) — one clock
end-to-end, matching warmup, the corpus, and the research hours; the
`tick_store` "far future" junk guard widened from +1h to +4h so legit
server-stamped (+3h) live ticks aren't dropped.  Verified: journal goes
monotonic on the server clock (12:57→13:00 per-minute skips), gate names
server hours, and the pass now opens its window when SERVER hour ∈
[18,24) = local UTC 15:00-21:00 — reproducing the backtest cell exactly.
Regression test: `test_subscribe_ticks_stamps_terminal_clock_not_local`
in `tests/test_mt5_client_hardening.py`.

**JOURNAL WATCHDOG (2026-08-12) — the stall that silently missed windows:**
the pass keeps stalling in dead chunks (process alive, MT5 connected, no
journal writes — the recurring IPC pattern), and before this a stalled pass
could sit silently for hours and miss the 18-24h window.  Now scheduled:

- `mql5/forward_demo_watchdog.py` — checks `journals/forward_demo_18_24.jsonl`
  (file MTIME = wall clock, so the +3h server stamp can't bias the age).
  Exit codes: 0 healthy, 1 STALLED (> 30 min silent — alert written, once
  per stall episode via a state file), 2 journal missing.  A pass with its
  full 30 closed trades is reported COMPLETE, not stalled.  Alerts carry
  the diagnosis (age, outcomes, pass process alive?, terminal up?) and the
  restart command; log: `.freebuff/forward_demo_watchdog.log`.
- Task Scheduler entry **"Mitemshub ForwardDemo Watchdog"** — every 15 min:
  `schtasks /query /tn "Mitemshub ForwardDemo Watchdog" /v /fo LIST` to
  check Last Result (0 = healthy, 1 = stall detected).  Scheduler output
  goes to `.freebuff/forward_demo_watchdog_sched.log`.

Verified live on 2026-08-12: the watchdog fired on the real stalled pass
(102 min silent, pass alive in a dead chunk), the pass was restarted
(pid via `tasklist | grep python`), the journal went fresh again, and the
watchdog flipped to `status=OK` with the scheduled task returning 0.

**Time-exit exit mode ported to the tester + 6-month backtest (2026-08-12):**
`BandBackTests` gains `InpExitMode` (0 = TARGET default; 1 = TIME) — the
Python time-exit policy: exit at the 1R stop or the hold-horizon close,
target ignored entirely, breakeven trail disabled, mirroring the harness
`TimeExitCapturePaperBroker` byte-for-byte.  Backtest on the 6-month window
(SYN75 M5, fresh-window re-run):

| exit | hold | n | hit | exp gross | total gross | tot net@0.05 | tot net@0.10 |
|---|---|---|---|---|---|---|---|
| TARGET | 1h | 1,537 | 25.4% | +0.016R | +24.6R | −52.3R | −129.1R |
| **TIME** | **1h** | **1,355** | **15.1%** | **+0.125R** | **+169.4R** | **+101.6R** | **+33.9R** |
| TIME | 2h | 1,245 | 13.3% | +0.005R | +6.2R | −56.0R | −118.3R |
| TIME | 3h | 1,160 | 12.8% | +0.017R | +19.7R | −38.3R | −96.3R |

**TIME@1h is the first clearly positive cell on the 6-month window:**
+0.125R/trade (≈8× the TARGET baseline's +0.016R), +169.4R total gross,
and it clears realistic costs — +101.6R total net@0.05, still +33.9R at
0.10 cost.  Exit mix confirms the port: TARGET 74% stop / 26% target /
0% time vs TIME 86% stop / 0% target / 14% time (the 14% are the
hold-horizon closes).  The horizon optimum on the MQL5 band leg is 1h —
unlike the Python UTC-gated sniper leg (where 3h won total net): the
ungated band leg is ~70% deep extensions whose drift mean-reverts within
~1-2h (2h collapses to +0.005R, 3h recovers only marginally), while the
Python leg's gated shallow entries carry a longer-lived drift.  The
mid-depth fades carry the TIME edge (1.5-2.5 at 1h: exp +0.335R, sumR
+96.6R).  Caveats: one 6-month window, single position, and the TIME hit
(~13-15%) is structurally lower than TARGET's — expectancy is the right
lens, not the target-hit floor.

**Also fixed — the depth-split CI is now exit-mode-aware:** TIME mode's
hit (~13-15% positive-R closes) sits below the TARGET-calibrated [15,60]
band while expectancy is HIGHER, so the check false-failed every TIME
cell.  `Test-DepthSplit` now reads the run block's `exit_mode` and
applies a [5,60] hit band to TIME runs (still catches the ~2%
trail-disaster class); unit fixtures + end-to-end PASS verified.

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

**Real-corpus cross-validation (2026-08-12):** `phase6_real_corpus_check.py`
closes the same gap the Phase-2/3 harnesses closed — a STATEFUL replay of the
risk layer over the real R_75 tick corpus (2378 M5 bars / 198h, 2078
signals), instead of only the stateless parity gate.  Both engines consume
the same deterministic signal stream (3-bar momentum direction, RR 1.2,
closed-candle stop/target, 1h time exit) and the SAME Python-driven position
lifecycle, so every downstream divergence is a gate/threshold/counter
difference.  Results:

- **`--mode aligned`** (shared gates at Python RiskConfig values): **veto
  agreement 2078/2078 (100%)**, per-gate veto tallies identical gate-for-gate,
  stake parity 202/202, stateful parity (streak + daily-dd + open counts)
  2078/2078, 0 day_start disagreements.  The MQL5 risk layer and the Python
  RiskEngine behave identically on the shared gates.
- **`--mode defaults`** (MQL5 Constants.mqh vs Python RiskConfig): veto
  agreement 81.4% (386 disagreements) — every one attributed to documented
  configuration drift, none unexplained.  Python is stricter on daily loss
  (2% vs 5%: 131) and consecutive losses (4 vs 5: 130); MQL5 adds hard caps
  Python lacks — trades/day 10 (109), trades/hour 3 (8), the
  decision-layer WEAK veto (8).  Stateful parity stays 2078/2078 and stake
  parity 77/77 even at defaults.
- The 1.2-RR float boundary is exercised and SYMMETRIC: both sides compute
  `reward_risk` from the same entry/stop/target floats, so the 150
  boundary-adjacent vetoes agree on both sides.

Two harness findings worth carrying into Phase 7: the consecutive-loss
breaker is a per-day hard lock (4 material losses halts the engine until the
next session-day rollover re-arms it — nothing else resets a locked streak),
and Python's `sync_session_day` lazily primes on first call, so a consumer
that never calls it before the first day change silently skips the first
daily reset (the harness must prime it, exactly like production does).

### Phase 7 — Execution layer (2026-08-12)

The six Execution modules are in place (`OrderManager`, `StopManager`,
`TakeProfitManager`, `PositionManager`, `ExecutionMonitor`, `ExecutionEngine`),
compiled clean (0 errors, 0 warnings) and **119/119 in the Strategy Tester**
(`Tests/Phase7Tests.mq5` on SYN75, SUITE PASSED).  The layer is
**transport-injected**: production binds the real `CTrade` via `CTradeAdapter`;
the tester binds `MockTrade` with scripted retcodes — so the mocked-retcode
phase gate (rejection / invalid stops / volume errors / margin /
verify-fill failure) runs headless and the same engine code runs live
unchanged.  `OrderManager` verifies every fill against the position table (and
that closes actually removed the position); `ExecutionEngine` gates spread,
price sanity, stops-level, and min-RR before the transport is touched;
`PositionManager` only evaluates closed candles (no intraday-wick stop-outs)
with reason-coded breakeven-trail / time-exit / partial management — the same
closed-candle grace the Python engine enforces.  `verify_all.ps1` picks the
suite up automatically via `Tests/*Tests.mq5`, so Phase 7 is already part of
the one-command loop.

### Phase 7 real-corpus cross-validation (R_75, 2026-08-15)

`phase7_real_corpus_check.py` runs the execution layer against the REAL
production Python backend over the real tick corpus — the Phase-2/3/6 harness
pattern applied to execution.  2303 deterministic RR-1.2 signals from real R_75
M5 bars (2603 / 217h) feed the MQL5 Execution mirror and the
`SimulatedExecutionBackend` (the backend `paper_runner.py` journals).

**Aligned mode (shared config: gates off, wick exits, no trail, 1h time exit):
100% parity on all 1012 traded entries** — identical entry bar, exit reason,
exit price and realized R (577 STOP / 427 TARGET / 8 TIME on both sides), and
the min-RR 1.2 float boundary agrees exactly (972 below-threshold signals,
0 disagreement).

**Defaults mode (honest divergence):** the execution gates veto 997/2303
signals (957 = the RR-1.2 float boundary — Python would submit all; 31 =
spread guard on real corpus spreads; 9 = price sanity), and on the same
approved entry set the Python journal (wick, no trail) books **−84.8R over 764
trades** while the MQL5 closed-candle + BE trail books **+102.2R over 727
trades** — 201 wick-stops spared by the grace, 259 −1R losses converted to
scratch by the trail.  The band's full production floor (min_rr 2.0) rejects
ALL RR-1.2 signals by design.  `[PHASE7-REAL]` machine lines are wired into
`verify_all.ps1` as part of the `RealCorpus` gate contract (see the gate
section above) — aligned parity below 100% or a defaults-mode edge flip now
fails the scheduled loop.

## Phase 8 — Journal + Analytics (2026-08-15)

`Journal/` and `Analytics/` give the engine the plan's §17/§18 traceability:

- **`Journal/TradeJournal.mqh`** — the §33 machine-readable trade log.  One CSV
  row per closed trade: opened_at, symbol, strategy, regime, direction, entry,
  SL, TP, volume, risk, pnl, confidence, score, exit, R, MAE, MFE, exit_reason,
  closed_at, hold_bars.  Writes FILE_TXT + hand-built rows (FILE_CSV's auto-
  quoting is unreliable in the tester sandbox); `CsvEscape` (in
  `Constants.mqh`) sanitizes reason strings.
- **`Journal/DecisionLogger.mqh`** — every BUY/SELL/WAIT with the full
  decision-layer context (verdict, confidence, composite, geometry, reasons) in
  a ring buffer + optional CSV mirror, with the §24 debug print block.
- **`Journal/PerformanceLogger.mqh`** — incremental run aggregation (net/gross
  PnL, PF, expectancy, win rate, avg win/loss, max drawdown on the
  cumulative-R curve, consecutive streaks, avg hold) with a per-run summary CSV.
- **`Analytics/PerformanceAnalytics.mqh`** — the full §18 metric set over
  `OutcomeRecord[]` (identical math to the logger) plus splits by strategy,
  regime, direction, exit reason, and confidence bucket.
- **`Analytics/ExpectancyEngine.mqh`** — hit rate, avg R, avg planned RR, and
  the empirical break-even floor (exact stage3_gate port: 1/(1+RR)+margin,
  clamp [0.10,0.60], fallback 0.50) with a BEATS / does NOT beat verdict.
- **`Analytics/RegimeAnalytics.mqh`** — per-regime breakdowns, best/worst
  regime, regime concentration, and alignment share.

**Verification (2026-08-15):** MetaEditor compile 0 errors / 0 warnings;
`Tests/Phase8Tests.mq5` green in the real Strategy Tester on SYN75
(**87 passed, 0 failed — SUITE PASSED**): the CSV round-trips (write → close →
reopen → read back, header not duplicated), the logger matches hand-computed
aggregation (max-DD 4.0R, PF 0.75, streaks 2/2), analytics metrics agree with
the logger, all five splits are locked, the break-even floor math is pinned,
and the regime breakdowns check out.  `verify_all.ps1` picks the suite up
automatically.

## Phase 9 — UI (2026-08-15)

`UI/` renders the plan §34 chart dashboard and the trade/analysis trail on the
chart.  Every object the engine draws goes through ONE lifecycle manager, so
the object count is provably bounded and leak-free:

- **`UI/Panel.mqh`** — the object-lifecycle foundation: a fixed-capacity named
  registry with lazy ONE-TIME creation (create once, then update-only), a text
  cache so content is assertable headlessly, and per-object teardown.  Bound:
  `UI_MAX_OBJECTS` (256) per panel, `UI_MAX_MARKERS` (64) per signals ring.
- **`UI/Dashboard.mqh`** — the §34 block: SYMBOL / MODE / REGIME (+conf) /
  HTF BIAS / STRUCTURE / VOLATILITY / STRATEGY / SETUP SCORE / EXPECTED RR /
  DECISION / RISK / SL / TP / OPEN POSITIONS / TODAY / DRAWDOWN / REASON,
  color-coded by decision (BUY lime, SELL tomato, WAIT gray) and regime, with
  an EMERGENCY_STOP banner on hard halt.  Fixed 20-object table; `Update()` is
  text-only.  `FromStateManager()` feeds it straight from the engine state.
- **`UI/VisualSignals.mqh`** — the reason-coded marker ring: entry/exit arrows
  (233/234), SL/TP/breakeven HLINEs, structure/liquidity markers, regime-
  change VLINEs.  Bounded by construction — adding beyond the 64-slot cap
  evicts the oldest, and slot reuse type-switches the object (delete +
  re-create) so the count never grows.

**The object-count tester gate** (Phase9Tests) enforces the leak contract:
registry bounded and stable across thousands of updates, identical object
counts across create/destroy generations, real `ObjectCreate` attempts never
above the caps, and every registry empty after teardown.  Three MQL5 gotchas
found while building it: (1) the Strategy Tester does NOT release chart
objects mid-pass — neither `ObjectDelete` nor `ObjectsDeleteAll` decrements
`ObjectsTotal` during a pass (the tester auto-cleans at pass end), so the gate
is registry-level, and `DestroyAll()` per-object delete is correct for live
terminals; (2) this MT5 build exposes `OBJPROP_TIME` as an INTEGER property
(`ObjectSetInteger`), verified by probe compile; (3) MQL5 forbids in-class
`static const` members, so layout constants are `#define`s.

**Verification (2026-08-15):** MetaEditor compile 0 errors / 0 warnings;
`Tests/Phase9Tests.mq5` green in the real Strategy Tester on SYN75
(**94 passed, 0 failed — SUITE PASSED**): panel lifecycle, the full §34 layout
formatting + long-field truncation, the StateManager feed, the bounded marker
ring with type-switch reuse, and the object-count gate.  `verify_all.ps1`
picks the suite up automatically.

## Phase 10 — Integration step 1: Market feed modules (2026-08-15)

The two feed modules the EA needs that no production file had yet, extracted
from `Tests/BandBackTests.mq5` so the EA never depends on a test suite:

- **`Market/GarchForecaster.mqh`** — the EGARCH(1,1) estimator, verbatim
  (modes: 0 = online-SGD faithful port of Python `models/garch.py`, 1 =
  calibrated-fixed with the R_75 parameters — the production estimator).
  Buffer-initialized log-variance at 50 observations; `Update()` returns false
  with sigma = sqrt(long_run_variance) during the <30-observation warmup,
  exactly like Python `_default_features()`.
- **`Market/BarAggregator.mqh`** — the tick→closed-bar bucketter matching the
  Python `CandleBuilder` convention: `bucket = floor(time/bar_sec)*bar_sec`,
  same-bucket ticks update OHLC, a bucket crossing closes the bar exactly once
  (`OnTick` returns true → `ClosedBar()` consumes it), multi-bucket jumps
  fabricate no empty bars, and stale ticks are ignored.  This is the
  closed-candle discipline the EA's per-bar pipeline runs on.

**The Phase-10 step-1 lock (Phase10Tests):** reference sigmas are LOCKED
cross-language, not just smoke-tested.  `mql5/phase10_garch_reference.py`
runs the REAL Python `EGARCHVarianceForecaster` (mode-0 lock) and a
fixed-params replication (mode-1 lock) over a fixed 80-return sequence
(self-validating its mode-0 replication against the actual model before
printing), and the tester asserts every MQL5 sigma against those literals at
1e-9 relative.  Any divergence — a mistranslated recursion, a wrong clamp, a
drifted default — fails the suite visibly.

**Verification (2026-08-15):** MetaEditor compile 0 errors / 0 warnings;
`Tests/Phase10Tests.mq5` green in the real Strategy Tester on SYN75
(**620 passed, 0 failed — SUITE PASSED**): the <30-observation warmup gate,
mode-1 calibrated-fixed sigmas vs the fixed-params replication (all 80),
mode-0 online-SGD sigmas vs the real Python forecaster (all 80), SGD-vs-fixed
divergence, determinism across instances + Reset, and the aggregator's OHLC /
exactly-once close / multi-bucket jump / stale-tick / lockstep semantics.

## Phase 10 — Integration step 2+3: the EA + P10-A aligned (2026-08-16)

**`MitemshubAI.mq5`** — the integrated EA: `OnTick` → `BarAggregator` →
`CandleEngine` → `GarchForecaster` → `VolatilityEngine` → `RegimeEngine` →
`StructureEngine` → `StateManager` → band gate → `ScoringEngine` /
`ConfidenceEngine` decision layer → `TradeQualityEngine` stage-3 floor →
`RiskEngine` → `ExecutionEngine` (paper transport) → `TradeJournal` /
`DecisionLogger` / `PerformanceLogger` → `Dashboard` → `VisualSignals` →
`PositionManager` per-bar management.  Wrapper `Tests/Phase10IntegrationTests.mq5`
lets verify_all.ps1 compile and run it like every other suite.

**Verified (2026-08-16):** MetaEditor compile 0 errors / 0 warnings;
Strategy Tester on SYN75 runs the FULL pipeline and emits the `[PHASE10]`
machine lines (`trades / exit split / sumR / hit / avg_rr / floor / verdict /
vetoes / rejects`) plus `SUITE PASSED`; the whole loop is green in
`verify_all.ps1` including the new `Phase10Gate` row.

**P10-A finding — the engine is aligned, the DATA sources are not.**  The
Python reference (`backtest-vol --mode band` on the corpus, 300s) fires 28
signals on the 2,565 M5 candles the corpus contains; the EA fires 93 on the
4,584 dense M5 bars the tester generates for the same window.  The gap is a
DATA-source mismatch, not an engine bug: the `data/backfill/R_75_ticks.csv`
corpus is ~50% sparse (full Aug 1-5, then only 17-145 M5 buckets/day from
Aug 6-16) while the terminal's SYN75 cache is full-density.  Measured proof:
on the shared full-density days (Aug 1-5) the EA fires **22 signals vs
Python's 23** — near-parity; the divergence is entirely the sparse tail,
where the EA sees 5-10x more bars and fires proportionally.  Same-data
parity is therefore not enforceable until the corpus is complete.

**The P10-A gate is data-aware by design.**  `Invoke-Phase10Gate` in
verify_all.ps1 always enforces the internal contract (exit split sums to
trades, floor verdict self-consistent, zero vetoes/rejects in aligned mode,
RR ≥ 1) and a RATE guard (EA signals per tester bar vs CLI signals per corpus
candle within [0.25, 3.0]); when the corpus is ≥80% dense it additionally
enforces the STRICT contract (trades ±10, hit ±5pp, sumR sign, floor
verdict).  `-SkipPhase10Gate` opts out.

**R_100 four-leg sign-lock (inside the same gate, 2026-08-16).**  The gate
also runs the R_100 four-leg head-to-head (`backtest-vol --mode band
--compare` @300s on `data/backfill/R_100_ticks.csv`) and FAILS if any leg's
expectancy flips non-negative relative to the documented P10 matrix — the
matrix locks ALL FOUR R_100 legs as negative (band −0.591R / fade −0.198R /
momentum −0.019R / sniper −0.029R).  A flip means the matrix reference is
stale or the leg's edge / cost model changed materially, so the loop must
fail visibly instead of silently carrying a stale reference.  The parse is
keyed on the CLI's `strategy=` machine lines (band / vol-reversion /
vol-momentum / sniper), requires all four legs present with a parseable
`expectancy_r=`, and only asserts the sign when a leg actually traded
(>0 trades — a 0-trade leg can't prove a flip).  `-SkipPhase10R100Gate`
opts out of this sub-check only (the four-leg run replays the sniper via
`run_ticks`, the slow leg of the head-to-head).  Verified end-to-end on
2026-08-16: the sign-lock PASSes on the fresh run (sniper n=266 −0.043R,
band n=81 −0.591R, momentum n=199 −0.019R, fade n=41 −0.198R — all
negative) and the FAIL branch was proven on a synthetic flipped momentum
leg (+0.047R → SIGN FLIP).

**R_75 sign-lock (inside the same gate, 2026-08-18).**  The gate also
asserts the R_75 CLI reference's OWN sign against the documented matrix
(−0.393R on the aligned real-tick basis, 2026-08-17): a non-negative
expectancy on the band reference fails the loop even when EA↔CLI trade
parity stays inside tolerance.  The STRICT branch only checks EA-vs-CLI
sign *agreement* — a flip that moves BOTH sides positive together (a
re-baseline, a cost-model edit, or a systematic edge change) satisfies
parity and would otherwise pass silently.  Mirrors the R_100 four-leg
sign-lock (which pins the leg signs against the P10 matrix); the R_75
block reuses the already-computed CLI reference, so it adds no runtime.

**Corpus repaired (2026-08-16) — the STRICT branch is now ACTIVE.**  The
sparse tail (Aug 6-16, 50-145 buckets/day, Aug 10/11/14 missing entirely)
was backfilled from the terminal's own M1 history with
`python -m synthetic_trader.scripts.repair_corpus --symbol R_75 --backup`:
47,372 OHLC-exact ticks (4 per M1 candle, 5 M1 candles per M5 bucket) merged
into the 2,369 previously-missing buckets, keeping every real tick verbatim.
Density: **0.491 → 0.935** (2,602 → 4,968 unique M5 buckets; the residual
~6% is the corpus edges — Jul 30 starts at 05:41 and Aug 16's M1 sync ends
12:34 UTC).  First strict run:
`density=0.935 STRICT: EA n=97 hit=2.06% sumR=-36.172 | CLI n=90 hit=2.22%
exp=-0.309` — **PASS** (trades Δ=7 ≤ 10, hit Δ=0.16pp ≤ 5, sign agrees).
On the shared full-density days the EA now fires 97 vs CLI's 90 — same-data
parity, no more 3.3x over-firing.  The repair is repeatable (the script
fetches the terminal's M1 range over the corpus span and only fills buckets
with <4 ticks), so a future collector outage can be repaired in one command.

**P10-A strict reference re-baselined (2026-08-17) — the last red row is
green.**  After the corpus kept growing (Jul 30 04:41 → Aug 16 20:33, density
0.933), the full-loop STRICT pair sat at **EA 98 vs CLI 87 (Δ11 > 10)** —
one trade over the Δ≤10 tolerance.  The Δ was NOT a density artifact: the
CLI reference ran with the DEFAULT risk config (consecutive-loss halt 4,
daily-loss halt 2%), which vetoed 16 of 103 signals — a 1.15%-hit 4R
strategy trips the 4-loss breaker after every few losses and stays halted
until the next win — while the EA's aligned mode approves every signal
(InpMaxConsecLosses=9999 / InpMaxDailyLossPct=1.0 — "reference approved
every signal — limits permissive", by the EA's own comment).  Full-density backfill was ruled out as a fix: the corpus's
residual gaps are real data boundaries (Jul-30 04:41 start, Aug-16 20:33
end — no ticks exist beyond them) and the interior 11:00–11:55 UTC holes on
Aug 1/8/15 exist in the terminal's OWN M1 history (measured via
`copy_rates_range` — the cache ends at 10:59 those days), so they cannot be
re-created from any source.

**Re-baseline:** the P10-A gate's CLI reference now runs the anchored-fit
band in the SAME aligned mode as the EA — `backtest-vol --mode band
--max-consecutive-losses 9999 --max-daily-loss-frac 1.0` (r_75.json still
loaded).  On the current corpus that reference gives **trades=102
signals=103 rejected=1 win=0.98% exp=-0.393** (the one rejection is an
open-position overlap, the EA's SetMaxOpenPositions(1) equivalent).  The
accepted pair is therefore:

| Side | trades | hit | sumR / expectancy |
|---|---|---|---|
| EA (SYN75 M5, tester cache, aligned) | 98 | 1.02% | −36.964 |
| CLI reference (R_75 band @300s, aligned risk, anchored fit) | 102 | 0.98% | −0.393R |

**STRICT: PASS** — trades Δ4 ≤ 10, hit Δ0.04pp ≤ 5pp, sumR/expectancy both
negative, EA floor verdict NOT_BEAT self-consistent, vetoes/rejects 0.  The
residual 4-trade gap is the honest data-boundary residue (CLI sees the
Aug-16 tail past the tester's Aug-16 00:00 window; EA sees Jul-30 00:00–04:41
bars the corpus predates) — small enough to sit inside the tolerance the
contract was designed for.  The P10-E sign gate's CLI reference uses the
same aligned command; the R_100 four-leg sign-lock matrix is unchanged (it
locks the SIGN on realistic costs, a separate basis).

**Also fixed while wiring:** the EA's `MeanRevertSignal` was missing Python's
middle z-band branch (2.0-3.0 → `min(0.6, 0.3 + recent*0.05)`) — patched for
exactness (entry-set-neutral at the 0.02 min-revert gate, but the port is now
faithful).  And the six undeclared `GATE_*` constants (defined in
BandBackTests but not the EA) plus an implicit enum conversion — the
transitional compile had 6 errors / 1 warning; now 0 / 0.

## Phase 10 — P10-D row: the EA on SYN100, sign-lock vs Python R_100 (2026-08-16)

**Run:** `verify_all.ps1 -Suite Phase10IntegrationTests -Symbol SYN100
-RangeDays 17 -Inputs "InpGarchMode=0;InpGarchOmega=-1.8412;InpGarchAlpha=0.1345;
InpGarchGamma=-0.0374;InpGarchBeta=0.8557"` (Python gates skipped — P10-D's
reference is the R_100 band, not R_75).  The EA seeds mode 0 (online-SGD from
calibrated priors — exactly the Python `calibrated_garch=loaded` path) with
the fresh R_100 params and runs on the SYN100 tester cache over the same
17.4-day window as the corpus.

**Result — P10-D PASSES (sign-lock confirmed):**

| Side | trades | hit | sumR / expectancy | calibration |
|---|---|---|---|---|
| EA (SYN100 M5, tester cache) | 106 | 0.94% | **−53.741** | mode-0 seeded (omega −1.8412 / alpha 0.1345 / gamma −0.0374 / beta 0.8557) |
| Python reference (R_100 band @300s, repaired corpus) | 81 | 3.70% | **−0.591** | loaded (`r_100.json`) |

Both sums are **negative** — the P10-D contract (sign agreement, expected
negative) holds.  The 106-vs-81 trade gap is the same data-source mismatch
documented for P10-A (terminal cache full-density vs corpus) rather than an
engine divergence; P10-D locks the SIGN, not trade-for-trade parity.  The
reference number was updated after the corpus repair (was 44 trades / −0.619R
on the sparse corpus).  The EA run also kept internal consistency (exit split
sums to trades, floor verdict self-consistent, vetoes/rejects = 0) and
printed `SUITE PASSED`.

**Four-leg head-to-head on R_100 @300s, repaired corpus, realistic costs
(slip 0.05, penalty 0.10) — 2026-08-16, fresh calibrated params:**

| leg | trades | hit | expectancy | net PnL |
|---|---|---|---|---|
| vol-band (P10-D reference) | 81 | 3.70% | **−0.591R** | −254.51 |
| vol-reversion (fade) | 41 | 51.22% | −0.198R | −51.32 |
| vol-momentum | 199 | 33.67% | −0.019R | −48.60 |
| sniper (reference) | 262 | 46.95% | −0.029R | −60.23 |

All four legs are **negative** on R_100 at 300s — the R_100 side of the P10
matrix is uniformly bearish, and the band remains the sign-lock reference
the P10-D gate contracts against.  All three vol legs ran with
`calibrated_garch=loaded` (fresh `r_100.json`).

## Phase 10 — P10-D row: the EA on SYN75, sign-lock vs Python R_75 (2026-08-16)

**Run:** `verify_all.ps1 -Suite Phase10IntegrationTests -Symbol SYN75
-RangeDays 17 -SkipPhase10R100Gate -SkipSniperGate -SkipExecutionParity
-SkipRealCorpusGate -SkipPhase8Gate -SkipPhase6Gate -SkipCalibrationGate`
(Python gates skipped — this is the R_75 half of the P10-D sign-lock; the
R_100 half was verified earlier the same day).  The EA seeds mode 0
(online-SGD from calibrated priors — exactly the Python
`calibrated_garch=loaded` path) with the **anchored R_75 params as its
defaults** and runs on the SYN75 tester cache over the same 17-day window as
the repaired corpus.

**Result — P10-D R_75 PASSES (sign-lock confirmed):**

| Side | trades | hit | sumR / expectancy | calibration |
|---|---|---|---|---|
| EA (SYN75 M5, tester cache) | 98 | 1.02% | **−36.964** | mode-0 seeded (omega −1.8841 / alpha 0.1422 / gamma −0.0733 / beta 0.8527) |
| Python reference (R_75 band @300s, repaired corpus) | 87 | 1.15% | **−0.376R** | loaded (`r_75.json`) |

Both sums are **negative** — the P10-D contract (sign agreement, expected
negative) holds, the same verdict the R_100 half produced (EA −53.741 vs
reference −0.591R).  The EA init line confirms the shared anchored basis
(`[MITEMSHUB] bar_sec=300 garch_mode=0 omega=-1.8841 alpha=0.1422
gamma=-0.0733 beta=0.8527 ...`) — identical params to the CLI's `r_75.json`.
Machine line: `trades=98 exits=stop:39,trail:58,target:1,time:0 sumR=-36.964
hit=1.02% avg_rr=4.00 floor=25.0% floor_verdict=NOT_BEAT risk_vetoes=0
exec_rejects=0` (internally consistent — exits sum to trades, aligned mode
has zero vetoes/rejects).  The 98-vs-87 trade gap is the same data-source
mismatch as R_100 (tester cache full-density vs corpus 93.3% density); P10-D
locks the SIGN, not trade-for-trade parity.  The strict P10-A trade-count
contract still sits one trade over tolerance (Δ11 > 10) on that density gap
— the documented decision point from the full-loop run, unchanged by this
row.  **Resolved 2026-08-17** — the strict reference was re-baselined to the
anchored fit in aligned mode (permissive risk, matching the EA's 0-veto
aligned config) so the accepted pair is EA 98 / −36.964 vs CLI 102 /
−0.393R (Δ4 ≤ 10, STRICT PASS — see the P10-A section above for the
finding and why full-density backfill is impossible).  Both symbols in the
P10 matrix now share one freshly verified basis: R_75 (98 / −36.964 vs 102 /
−0.393R) and R_100 (106 / −53.741 vs 81 / −0.591R), all four sums NEGATIVE.

## Phase 10 — P10-B row: the EA at M1, 60s parity + a real risk-wiring bug (2026-08-16)

**Run:** `verify_all.ps1 -Suite Phase10IntegrationTests -Symbol SYN75 -RangeDays 17
-Inputs "InpBarSec=60;InpMaxConsecLosses=4;InpMaxDailyLossPct=0.02;InpMaxEquityDDPct=0.0"`
(Python gates skipped).  The Python 60s reference: `backtest-vol --mode band
--timeframe 60` on the repaired corpus = **signals 590, rejected 364, trades
226, win 9.73%, expectancy −0.166R**.

**First run exposed a real bug, not a parity miss:** the EA fired **523
trades / 0 vetoes** — its §12 risk breakers could not fire because outcomes
were never registered (`RegisterOpen`/`RegisterOutcome`/`RegisterClose` were
never called, and `SyncState(10000.0,…)` pinned equity flat on every bar, so
the consecutive-loss / daily-loss / equity-drawdown limits saw 0 losses
forever).  P10-A had masked this at 300s: Python's default risk rejected
14/104 signals there, but the EA's 0 vetoes passed the Δ≤10 tolerance.

**Fixed in `MitemshubAI.mq5` + `Risk/RiskEngine.mqh`:** (1) exit path now
registers outcomes — `pnl = stake × return_r` (Python `register_outcome`
parity), updates tracked equity, and `RegisterClose` clears the MQL5-only
exposure manager; (2) entry path calls `RegisterOpen` after a successful
submit; (3) a latent bug in the Evaluate reason chain — the equity-drawdown
(and open-positions / consecutive / daily) checks lacked the `> 0` guard
that `AnyHardLimitBreached` has, so a limit set to 0 (disabled) vetoed
EVERY signal.  Phase-6 suite still 45/45.

**After the fix — P10-B PARITY:**

| Side | trades | hit | sumR | vetoes |
|---|---|---|---|---|
| EA (SYN75 M1, default risk) | 238 | 10.08% | −38.840 | 318 |
| Python reference (60s band) | 226 | 9.73% | −37.5 | 364 rejected |

Trades Δ12, hit Δ0.35pp, sumR both negative and within 4% — same-data
parity given the residual corpus-density gap (93.5% vs the tester cache's
100%).  **P10-A strict gate still PASSES** after the fix (EA n=97 hit=2.06%
vs CLI n=90, vetoes 0 in the aligned config) — the 300s path is unchanged.
The production consequence: the EA's hard risk limits (§12 "TRADING
DISABLED") now actually fire instead of silently never tripping.

## Phase 10 — P10-C row: EA management config (trail 0.3 + closed-candle grace) vs the phase-7 defaults contract (2026-08-16)

**Run:** `verify_all.ps1 -Suite Phase10IntegrationTests -Symbol SYN75 -RangeDays 17
-Inputs "InpTrailOn=true;InpTrailFrac=0.3;InpClosedCandleGrace=true"` with the
gates skipped (P10-C is a manual row like P10-B/D — the P10-A gate expects its
own aligned config).  The EA now defaults to the anchored R_75 calibration
(omega −1.884103 / alpha 0.142169 / gamma −0.073285 / beta 0.852741) and
reuses the fixed risk wiring from P10-B.

**Phase-7 defaults-mode contract (the Python harness, same entry set, both exit
policies) — PASS (re-verified 2026-08-16, fresh run on the current corpus):**

| lane | trades | hit | sumR |
|---|---|---|---|
| Python wick journal (no trail) | 1604 | — | **−28.99** |
| MQL5 closed-candle + BE trail 0.3 | 1528 | 31.1% | **+257.26** |

sumR_mq +257.26 > sumR_py −28.99 ✓, grace_saved 401 + trail_converted 571 > 0 ✓
(numbers moved up from the gate's original +104.6/−82.4 because the corpus is
now full-density — more bars, more replays; the contract direction holds).

**EA side (SYN75 M5, 17-day window, grace=ON verified in the machine line):**

| EA run | trades | exits (stop/trail/target/time) | sumR | vetoes/rejects |
|---|---|---|---|---|
| P10-A baseline (wick, trail 0.3) | 97 | 39/56/1/1 | −36.172 | 0/0 |
| P10-C (grace ON, trail 0.3) | 98 | 39/58/1/0 | −36.964 | 0/0 |

The management wiring is end-to-end live in the integrated EA (grace=ON
applied, 58 BE-trail conversions > 0, zero vetoes/rejects with the fixed risk
engine).  The honest nuance: on the **band** entry set the closed-candle grace
is near-neutral (−0.79R on 98 trades — one exit reclassified time→trail and one
new trade), because the band's exits are time/trail-dominated and its stops are
rarely wick-touched.  The grace's value lives on the **sniper-style** entry set
with tighter stops — that's where the harness's 400 wick-saves come from.  So
P10-C confirms the phase-7 management edge contract (it PASSES), and confirms
the EA runs the same management config; it also documents that the grace is an
entry-set-dependent tool, not a band-leg fix.

## Phase 10 — P10-E row: OHLC stress — the direction FLIPS (2026-08-16)

**Run:** `verify_all.ps1 -Suite Phase10IntegrationTests -Symbol SYN75 -RangeDays
17 -TestModel 2` (gates skipped; the `-TestModel` override applies to the suite
loop only — the Phase-6 risk gate and the seed sweep keep `Model=1` because
their contracts were calibrated on real ticks).  Same window, same EA inputs,
same anchored calibration — only the tester's price model changed:

| EA run | model | ticks | trades | hit | sumR |
|---|---|---|---|---|---|
| P10-A baseline | 1 (real ticks) | 97,200 | 98 | 1.02% | −36.964 |
| **P10-E stress** | 2 (1-min OHLC) | 19,039 | 96 | **30.21%** | **+55.502** |

**The P10-E row criterion ("same PnL direction") is NOT met — the sign
flipped from negative to positive.**  This is a real, reproducible finding, not
a fluke: the run generated 19,039 OHLC-synthesized ticks vs 97,200 real ticks
over the same 4,860 M5 bars, so the tester genuinely used the OHLC model.

**Why it flips — and why this matters:** the OHLC model only sees 1-min bar
closes, so intrabar wick trade-throughs never reach the EA's stop logic.  The
band's 4.0σ target becomes reachable on closes (hit 1.02% → 30.21%) and the
−36.964R real-tick loss becomes +55.502R.  In effect, OHLC implicitly applies
closed-candle grace to ALL exits — the same mechanism P10-C measured as
near-neutral on the band leg because its stops are rarely wick-touched on real
ticks.  The honest conclusions:

1. **The band's negative real-tick result is model-true.**  The direction flip
   under OHLC means the positive sign is a *model artifact* — you cannot
   validate the band leg on OHLC and call it profitable; only real-tick tests
   are trustworthy for this geometry.
2. **The flip quantifies the grace ceiling.**  +55.502R vs −36.964R (Δ≈92R
   over 96-98 trades) is the theoretical value of applying wick-grace to
   stops — a useful upper bound for the sniper-side grace work, not a band
   freebie (the band's own P10-C grace run stayed at −36.964R because its
   stops aren't the wick-hit exits; the OHLC delta comes from the *entry set's*
   stop sensitivity, which is the sniper geometry's domain).

   **Follow-up — the sniper does NOT flip under the OHLC model.**  There is no
   sniper EA in the tester (the sniper is Python research via `run_ticks`), so
   the equivalent was a replay of the REAL captured 277-trade sniper entry set
   under close-based exit resolution — the documented P10-E mechanism (no
   intrabar wick trade-throughs) — at both the native M5 and the tester's 1-min
   resolution (`_probe_sniper_ohlc.py`):

   | lane | trades | hit | sumR | delta vs real ticks |
   |---|---|---|---|---|
   | WICK-M5 (real ticks) | 277 | 50.2% | +121.40 | — |
   | CLOSE-M5 (OHLC-equiv) | 277 | 50.2% | +119.09 | **−2.31R** |
   | CLOSE-M1 (1-min OHLC) | 276 | 50.4% | +119.86 | **−1.54R** |

   The band's ~92R OHLC delta is a **band-geometry artifact, not a general
   wick-grace value**: the sniper's 1R stops mean 135-136 of its 136
   stop-outs are CLOSE-THROUGHS even at 1-minute resolution (the close itself
   violates the stop), so removing intrabar wick trade-throughs converts
   almost nothing (0-1 of 136).  The band's 4.0σ target makes its stop the
   near side, so its stop-outs are wick-only touches that the OHLC model lets
   survive to the reachable target.  The sniper is model-robust in both
   directions (sign unchanged, sumR within ~2R of the real-tick baseline);
   the small negative deltas come from the close lanes missing wick-only
   *target* touches (132 -> 130-131 targets).  **The wick-save ceiling is
   therefore never sniper-harvestable:** the closed-candle grace is
   band-geometry-specific (wide stops, mostly wick-only touches), while the
   sniper's tight 1R stops are overwhelmingly close-throughs — close-based
   resolution converts ~nothing on the sniper entry set, so the ~92R ceiling
   must be read as the BAND's artifact, not a sniper improvement reserve.
3. **No state-growth concern:** 96 vs 98 trades (consistent volume), Phase-9's
   object-count gate is green (0/0) in the full loop, and the machine line
   still carries a clean internal contract (exit split sums, vetoes/rejects 0,
   floor verdict self-consistent).

## P10-E sweep: the FULL loop at -TestModel 2 (2026-08-17) — only the exit
## side moves, and a machine-line parse bug surfaced

Ran the whole loop (all 13 tester suites + every gate) at `-TestModel 2`
(`verify_all.ps1 -TestModel 2 -RangeDays 17`).  The result is remarkably
clean: **every suite and every Model-independent gate holds**, and the only
shifts are the two rows that consume the EA's `[PHASE10]` machine line —
which is exactly the P10-E lesson generalized.

| Row | Model=1 baseline | Model=2 result | verdict |
|---|---|---|---|
| All 13 tester suites (Phase1-9, Phase10, Phase10Integration, BandBack, StructureLive) | PASS | **PASS — byte-identical** | HOLDS |
| SniperGate | PASS | PASS (svcap n=277 exp +0.119R) | HOLDS (corpus replay) |
| ExecutionParity | PASS | PASS (40/40) | HOLDS |
| RealCorpus | PASS | PASS (phase6 aligned 4717/4717 veto 100%) | HOLDS |
| Phase8Gate | PASS | PASS (parity MATCH, band n=87 exp −0.376R) | HOLDS |
| Phase6RiskGate | PASS | PASS (242/294 — its own forced Model=1 run) | HOLDS |
| CalibrationGate | PASS | PASS | HOLDS |
| **Phase10Gate (P10-A STRICT)** | PASS (EA 98 vs CLI 102, Δ4) | **FAIL — hit Δ30.02pp + sign flip** (trades Δ2 still ≤10!) | SHIFTS (exit side only) |
| **Phase10ESignGate** | PASS | **FAIL — SIGN FLIP** (EA +60.496 vs CLI −0.393) | SHIFTS (expected) |

Two findings beyond the P10-E row itself:

1. **The entry set is model-robust; the EXIT side is what flips.**  At
   Model=2 the EA fired **100 trades vs the aligned CLI reference's 102 →
   Δ2**, even tighter than the real-tick Δ4: the band's ~100-signal entry set
   is price-model-independent.  What changes is entirely in the exits —
   hit 1.02% → 31.00%, sumR −36.964 → **+60.496**, floor verdict NOT_BEAT →
   BEAT, exit split 39/58/1/0 → 49/20/26/5 (targets become reachable on
   closes: 1 → 26; wick-trail conversions collapse: 58 → 20).  The STRICT
   trade-count check survives the model switch; hit/sign are the tripwires.
2. **The two machine-line gates had a parse bug that this sweep exposed:**
   the `[PHASE10]` regex required `sumR=([+-]...)`, but the EA prints a
   leading sign only for NEGATIVE sums — the first positive sumR in the
   suite-loop log (the Model=2 +60.496) made both gates bail with "no
   machine line" instead of evaluating the flip.  Fixed to `([+-]?...)` in
   verify_all.ps1 and re-evaluated against the actual run: P10-A now fails
   with the honest "STRICT hit Δ30.02pp + sign disagree" and P10-E with
   "SIGN FLIP" — the verdicts the contracts were designed to produce.
   (The R_100 four-leg sign-lock inside P10-A was skipped by the early
   bail; it is corpus-replay and Model-independent — unchanged from the
   verified 2026-08-16 matrix.)
3. **The audit generalizes the fix (2026-08-17).** The same sign-required
   assumption existed in every other numeric machine-line regex, two of
   them live: the Phase-6 risk gate's 60s `sumR=([+-]...)` would bail the
   first time that run's sumR printed positive or `0.000` (same EA, same
   no-forced-sign `%.3f` — only negative today by luck), and the Phase-8
   analytics gate's `beats=(yes|no)` could not match the harness's
   `beats=BEATS` (case-sensitive) — it only passed because the band has
   been losing; the first BEATS verdict would have bailed as "unparseable"
   instead of evaluating the flip.  All gate value-parses now share one
   token, `$NumTok` = `([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)`
   (defined once in verify_all.ps1 and seed_sweep.ps1): optional sign +
   exponent form, exactly one capturing group per use so downstream group
   indexes are unchanged.  The Phase-8 harness now emits `beats=yes|no` to
   match its gate's vocabulary.  Depth/vol-split and Phase-8 exp/sumR were
   `[+-]`-required but their emitters force `%+`/`:+` today — hardened to
   the same token so a dropped forced sign can never break them.  The fix is
   fixture-guarded: `verify_phase10_machine_line_fixtures.ps1` extracts the
   real `$NumTok` + all three gate regex literals and the real
   `Get-Phase10TradesLine` out of verify_all.ps1 and asserts a positive-sumR
   line (`sumR=60.496` — the Model=2 flip shape) parses end-to-end with
   correct groups, so P10-A / Phase-6 / P10-E evaluate it instead of bailing
   on "no machine line"; it also covers zero/forced-plus sumR, bar_sec
   last-run-wins scoping, and a negative control proving the old `([+-]...)`
   pattern still bails on the positive line (mutation-tested: regressing
   `$NumTok` back to a sign-required form fails the harness, exit 1).  The
   harness is wired into `verify_all.ps1`'s pre-flight as an always-on,
   ~1-second parse-contract gate (step 5): every verify run — including the
   hourly scheduled loop — executes it BEFORE anything compiles or stages, so
   a regex regression fails the run in seconds with `PRE-FLIGHT FAILED`
   (exit 2) instead of after a 20-minute tester run.  If the harness file is
   missing, the pre-flight warns loudly and proceeds (a missing harness   does not by itself produce a bogus verdict; restore it to re-arm the gate).
4. **The audit is now a closed loop (2026-08-17, same day).** Four follow-up
   guards landed so emitters and gates can never drift apart again:
   - **EA sign at the source:** the `[PHASE10]` print in MitemshubAI.mq5 now
     uses `sumR=%+.3f`, so every live machine line carries an explicit sign
     and the sign-optional `$NumTok` parse is a pure compatibility layer for
     old artifacts.
   - **Phase-8 fixture harness wired in:** `verify_phase8_machine_line_fixtures.ps1`
     (16 cases: live band/buckets/exit pattern extraction, beats vocabulary
     with a `beats=BEATS` negative control, forced-sign/no-sign/zero variants,
     emitter-source assertions on phase8_analytics_check.py) now runs in the
     same pre-flight step 5 as the Phase-10 gate.
   - **Phase-10 harness extended to every P10-A/P10-E value parse:** it now
     also extracts the CLI-reference patterns (`trades=` / `win_rate=` /
     `expectancy_r=`) and the R_100 four-leg block patterns (`^strategy=` /
     `^trades=` / `^win_rate=` / `^expectancy_r=`), asserts negative,
     no-sign-positive, and zero CLI expectancies parse, replicates the
     four-leg block parser against the documented matrix legs (band −0.591R /
     fade −0.198R / momentum −0.019R / sniper −0.029R), and negative-controls
     that a flipped (positive) leg is detected by the sign-lock.
   - **`$NumTok` fuzz gate (pre-flight step 6):** fuzzes every `$NumTok`
     interpolation site in verify_all.ps1 (9 rows: EA, depth, vol, phase7
     ×2, phase8 ×2, four-leg, CLI ref) against negative / no-sign positive /
     forced-plus / zero / small-exponent / large-exponent, plus a negative
     control that the old sign-required form still bails on a no-sign
     positive.  A table-vs-use-site text drift (each row's pattern must appear
     verbatim at ≥2 places in the file) fails the run, so a future emitter
     format change fails the loop in seconds instead of at the first live
     flip.
   - **The contract is documented once:** `MACHINE_LINE_SPEC.md` is the
     single source of truth — the shared number grammar, the sign policy per
     emitter, every emitter/parser pair with file pointers, the protection
     matrix, and emitter hygiene rules.

5. **Python-reference basis audit (2026-08-18).** Every place verify_all.ps1
   (or a harness it invokes) runs a Python reference was checked for a risk or
   config basis that could silently diverge from the contract it claims to
   enforce.  Findings and fixes:
   - **P10-A / P10-E `backtest-vol` references — FIXED:** both now pin the
     documented realistic-cost basis explicitly at the call site
     (`--entry-slippage-ticks 0.05 --exit-slippage-ticks 0.05
     --execution-penalty 0.10`) plus the aligned risk basis
     (`--max-consecutive-losses 9999 --max-daily-loss-frac 1.0`), so a future
     change to the CLI's *default* cost args cannot silently re-basis the gate.
     The CLI defaults currently match (0.05/0.05/0.10), but the gate no longer
     depends on them staying that way.
   - **R_100 four-leg reference — FIXED:** same explicit cost pin at the
     `--compare` call site (matrix basis is defined on 0.05/0.05/0.10).
   - **phase8_analytics_check.py internal CLI-parity reference — FIXED:** the
     Python-side broker hardcodes 0.05/0.05/0.10; the CLI subprocess now passes
     the same args instead of inheriting defaults.
   - **phase6/phase7 real-corpus checks — SAFE by design:** each runs in two
     explicit modes (`aligned` = shared gates configured identically, 100%
     parity enforced; `defaults` = MQL5-vs-Python drift quantified, parse-only
     row).  No silent basis: the contract mode is the aligned one and it fails
     loudly.
   - **execution_parity_check.py — SAFE by design:** uses zero-cost
     `PaperExecutionConfig()` on BOTH sides; the contract is paper-vs-live
     backend equivalence, so any cost basis would itself be drift.
   - **svcap_recheck.py — SAFE by design:** reports gross AND net@0.05 AND
     net@0.10 explicitly on the same run, gating on the costed cells; no
     hidden default.
   - **calibration_sanity_check.py / phase10_garch_reference.py — SAFE:**
     read on-disk calibration JSONs / a fixed literal sequence; no risk or
     cost args to drift.
   - **Windowed parity corpus (2026-08-18):** the R_75 reference corpus is now
     `data/backfill/R_75_ticks.windowed.csv` — union of the pre-repair head
     (Jul 30 → Aug 09) and the live backfill, repaired from the terminal's M1
     history, clipped EXACTLY to the tester window (Jul 30 00:00 → Aug 16
     00:00).  CLI 97 vs EA 98 (Δ1 ≤ 10, STRICT PASS); the live collector file
     keeps growing for the engine while the windowed file is the frozen parity
     basis.  The contract test `tests/test_phase10_aligned_reference_contract.py`
     locks this (|trades − 98| ≤ 10 and expectancy < 0 on the windowed
     corpus).

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
