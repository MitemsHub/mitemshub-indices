# Machine-Line Spec — emitters, parsers, and the shared number grammar

Single source of truth for every machine line this repo emits and parses, so
emitters and gates can never drift apart again.  If you change an emitter's
**format string**, you must update this table **and** the fixture/fuzz rows
that pin it — the verify loop fails in preflight if you don't.

Line numbers below are approximate (they shift as the files grow); the regex
text is the contract, the line numbers are a pointer.

## 1. The shared number grammar (`$NumTok`)

Defined once, in `mql5/verify_all.ps1` (top of file, ~line 90):

```
$NumTok = '([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)'
```

| Form | Example | Must parse |
|---|---|---|
| signed negative | `-36.964` | yes |
| positive, no sign | `60.496` | yes |
| forced plus | `+60.496` | yes |
| zero | `0.000` / `0` | yes |
| exponent | `-1.2e-05`, `6.0496e+01` | yes |
| leading-dot | `.5` | yes (grammar accepts it) |

**History (why it exists):** on 2026-08-17 the Model=2 sweep flipped the band's
`sumR` positive (+60.496).  The EA printed a leading sign only for *negative*
sums, the gates' regexes required `sumR=([+-]...)`, so both machine-line gates
bailed with "no machine line" instead of evaluating the flip.  The fix: the
shared optional-sign token above, plus the EA now prints `sumR=%+.3f` so every
live line carries an explicit sign and the optional-sign parse is a pure
compatibility layer for old artifacts.

**Sign policy by emitter** (what each emitter is *allowed* to print):

| Emitter | Format | Sign policy |
|---|---|---|
| EA `[PHASE10] trades=` (MitemshubAI.mq5) | `sumR=%+.3f` | forced `+` (as of 2026-08-17) |
| CLI `expectancy_r=` (cli.py) | `:.3f` | **no forced sign** — deliberately sign-optional |
| phase7 `sumR_py=/sumR_mq=` (phase7_real_corpus_check.py) | `:+.2f` | forced `+` |
| phase8 band/buckets `exp=/sumR=` (phase8_analytics_check.py) | `:+.3f` / `:+.2f` | forced `+` |
| BandBackTests depth/vol `exp=` (BandBackTests.mq5) | `%+.3f` | forced `+` |

**Rule:** every *parser* regex that consumes a number must use `$NumTok` (or an
equivalent optional-sign + exponent form).  A sign-required `([+-]...)` regex
is a regression — the fuzz gate (below) fails the loop on it.

## 2. Emitter / parser pair table

### A. EA tester-log lines (MQL5 → verify_all.ps1)

| Line | Emitter | Parser (verify_all.ps1) | Feeds | Pin |
|---|---|---|---|---|
| `[PHASE10] bar_sec=60 garch_mode=... trail=0.30 grace=OFF` | MitemshubAI.mq5:689 | `Get-Phase10TradesLine` (~1120, balanced-brace function) | P10-A / Phase-6 / P10-E line scoping | verify_phase10_machine_line_fixtures.ps1 |
| `[PHASE10] trades=238 exits=stop:100,trail:50,target:80,time:8 sumR=-36.964 hit=12.00% avg_rr=1.20 floor=30.0% floor_verdict=NOT_BEAT risk_vetoes=318 exec_rejects=0` | MitemshubAI.mq5:692-693 (`sumR=%+.3f`) | gate regex at 1244 (P10-A), 1497 (Phase-6 risk), 1548 (P10-E) | EA trade count / sumR / hit / floor / verdict / vetoes / rejects | verify_phase10_machine_line_fixtures.ps1 + fuzz row `EA [PHASE10] sumR` |

### B. CLI backtest-vol lines (Python → verify_all.ps1)

| Line | Emitter | Parser (verify_all.ps1) | Feeds | Pin |
|---|---|---|---|---|
| `trades=81` / `win_rate=3.70%` / `expectancy_r=-0.591` (stdout of `backtest-vol --csv ... --mode band`) | cli.py ~1072-1078 (`expectancy_r={:.3f}`, no forced sign) | 1277-1279 (P10-A CLI reference) | P10-A trade-count / hit / expectancy contract vs EA | verify_phase10_machine_line_fixtures.ps1 (`cli-ref-*`) + fuzz row `CLI reference expectancy_r` |
| `strategy=vol-band` + `trades=` / `win_rate=` / `expectancy_r=` blocks (stdout of `backtest-vol --compare`) | cli.py `_print_result` ~1161-1169 | block parser 1192-1199 (`^strategy=` / `^trades=` / `^win_rate=` / `^expectancy_r=$NumTok`) | R_100 four-leg sign-lock (P10 matrix) | verify_phase10_machine_line_fixtures.ps1 (`four-leg-*`) + fuzz row `R_100 four-leg leg expectancy` |

### C. BandBackTests lines (MQL5 → verify_all.ps1)

| Line | Emitter | Parser (verify_all.ps1) | Feeds | Pin |
|---|---|---|---|---|
| `[BANDBT]   depth <= 1.25:  n= 86  hit=31.4%  exp=+0.256R` | BandBackTests.mq5:1033 (`exp=%+.3fR`) | 373 and 722 | depth-split cells (≤1.25 / ≤2.00 floors) | verify_volsplit_fixtures.ps1 + fuzz row `BandBackTests depth-bucket exp` |
| `[BANDBT]   vol<=1.25    n=1527 hit= 25.3% exp=+0.014R sumR=+22.0R` / `vol>1.25 ...` | BandBackTests.mq5:1225+ (`exp=%+.3fR`) | 467 | vol-regime share / exp gate | verify_volsplit_fixtures.ps1 + fuzz row `BandBackTests vol-regime exp` |
| `[BANDBT] DEPTHPROFILE caps=... n=... hit=... exp=... share=... total=...` | BandBackTests.mq5 | 501 (uses `\S+` — format-agnostic) | depth composition | verify_volsplit_fixtures.ps1 |
| `[BANDBT] FLOORVERDICT floor=30.0 achieved=25.4 verdict=NOT_BEAT mean_rr=3.00` | BandBackTests.mq5 | 503 | floor gate | verify_volsplit_fixtures.ps1 |
| `[BANDBT] VERDICT: achieved hit 25.4% does NOT beat the 30.0% floor ...` | BandBackTests.mq5 | 426 | floor gate human line | verify_volsplit_fixtures.ps1 |

### D. phase7 lines (Python → verify_all.ps1)

| Line | Emitter | Parser (verify_all.ps1) | Feeds | Pin |
|---|---|---|---|---|
| `[PHASE7-REAL] mode=defaults bars=... signals=... approved=... vetoed=... trades_py=... trades_mq=... sumR_py=-36.96 sumR_mq=-36.96 grace_saved=12 trail_converted=8` | phase7_real_corpus_check.py:523-525 (`sumR_py/sumR_mq={:+.2f}` forced `+`) | 951-952 | phase7 defaults management-edge parity | fuzz rows `phase7 defaults sumR_py` / `sumR_mq` |
| `[PHASE7-REAL] mode=aligned bars=... signals=... parity=... trades_py=... trades_mq=... sumR_py=... sumR_mq=... rr_boundary_disagree=0` | phase7_real_corpus_check.py:452 | 951-952 (same `sumR_py=/sumR_mq=` tokens) | phase7 aligned parity | fuzz rows `phase7 defaults sumR_py` / `sumR_mq` |

### E. phase8 lines (Python → verify_all.ps1)

| Line | Emitter | Parser (verify_all.ps1) | Feeds | Pin |
|---|---|---|---|---|
| `[PHASE8-ANALYTICS] band n=65 hit=44.62% exp=+0.397R sumR=+25.81R maxDD=1.10R floor=30.0% beats=yes` | phase8_analytics_check.py:980-981 (`exp={:+.3f}R sumR={:+.2f}R`, forced `+`) | 1028 | band edge / floor / beats verdict | verify_phase8_machine_line_fixtures.ps1 + fuzz row `phase8 band exp/sumR` |
| `[PHASE8-ANALYTICS] buckets strong n=22 exp=-0.812R hit=18.18% \| weak n=59 exp=-0.509R hit=8.47%` | phase8_analytics_check.py:448 (`exp={:+.3f}R`) | 1029 | confidence-split edge | verify_phase8_machine_line_fixtures.ps1 + fuzz row `phase8 buckets strong/weak exp` |
| `[PHASE8-ANALYTICS] exit stop n=40 trail n=12 target n=21 time n=8` | phase8_analytics_check.py:988 | single-quoted `Match($exit, ...)` (~1030) | exit-type counts | verify_phase8_machine_line_fixtures.ps1 |

### F. CALIB / PARITY / GATECHECK / VERIFY string-contract lines

| Line | Emitter | Parser (verify_all.ps1) | Notes |
|---|---|---|---|
| `[SNIPER-OHLC] delta_max=2.31 threshold=5.00 verdict=OK wick_sumR=+88.16 close5_delta=-2.31 close1_delta=-1.41 wick1_delta=-1.41 band_ohlc_delta=+92.47` | _probe_sniper_ohlc.py (machine line, 2026-08-18) | Invoke-SniperOhlcGate (`delta_max=$NumTok ... band_ohlc_delta=$NumTok`, sign-optional) | sniper-OHLC model-robustness gate (fails if delta_max > ~5R) | verify_phase10_machine_line_fixtures.ps1 (`sniper-ohlc-*`) + fuzz row `sniper-OHLC delta_max` |
| `[CALIB] symbol=r_75 ok=1 omega=... alpha=... beta=... gamma=... persistence=... vol_ratio=... n=... reason=ok` + `[CALIB] summary ok=1 n=... reason=ok` | calibration_sanity_check.py:55-82 | 1006-1022 (string `ok=`/`reason=` contract, not `$NumTok`) | calibration sanity gate |
| `[PARITY] PASS|FAIL: ...` | execution_parity_check.py | 793 | string contract |
| `[GATECHECK] PASS|FAIL|SKIP: ...` | phase10_garch_reference.py | 844 | string contract |
| `[VERIFY] summary ok=1 rows=... green=... red=... skip=...` | verify_all.ps1:1989 (self-emitted) | run-mql5-verify-task.ps1 (email loop) | machine-readable ALL-GATES-GREEN line |

## 3. Protection matrix (what keeps this from drifting again)

| Protection | What it does | Where |
|---|---|---|
| `verify_phase10_machine_line_fixtures.ps1` | extracts the **live** `$NumTok` + all EA gate regexes + `Get-Phase10TradesLine` + CLI-ref/four-leg patterns out of verify_all.ps1 and asserts positive / zero / forced-plus / no-sign / exponent lines parse end-to-end; negative controls pin that sign-required and vocabulary regressions stay red | runs in verify_all.ps1 preflight (step 5) |
| `verify_phase8_machine_line_fixtures.ps1` | same treatment for band/buckets/exit: live pattern extraction, `beats=yes\|no` vocabulary (a `beats=BEATS` line must NOT parse), forced-sign / no-sign / zero variants, emitter-source assertions on phase8_analytics_check.py | runs in verify_all.ps1 preflight (step 5) |
| `verify_volsplit_fixtures.ps1` | extracts `Test-DepthSplit` and runs real BandBackTests log shapes through every branch | standalone + preflight-adjacent |
| `$NumTok` fuzz gate (verify_all.ps1 preflight step 6) | fuzzes **every** `$NumTok` interpolation site (9 rows: EA, depth, vol, phase7 ×2, phase8 ×2, four-leg, CLI ref) against negative / no-sign positive / forced-plus / zero / small-exponent / large-exponent; a table-vs-use-site text drift (count < 2) fails the run | verify_all.ps1 preflight |

## 4. Emitter hygiene rules

1. **Never require a sign** in a gate regex.  Use `$NumTok` (or an equivalent
   optional-sign + exponent form).  A `([+-]...)` pattern is a regression.
2. **Keep forced signs where documented** (EA `%+.3f`, phase7 `:+.2f`, phase8
   `:+.3f`/`:+.2f`, BandBackTests `%+.3f`).  The one deliberate exception is
   the CLI's `expectancy_r={:.3f}` — sign-optional on purpose; the parser and
   fixtures already accept both.
3. **Changing a format string** requires updating this table **and** the
   fixture(s) + fuzz row(s) that pin the line.  The drift check in the fuzz
   gate fails the loop if the regex text at a use site no longer matches the
   table.
4. **New machine line?**  Add it to this table, add a fuzz row (if it carries a
   `$NumTok`-style number) and a fixture case, and wire the fixture into
   preflight step 5.
