# ARM C — PAPER-TERMINAL TEMPLATE (built & parked 2026-09-05)

## What exists

| component | value |
|---|---|
| Install | `%LOCALAPPDATA%\MitemshubMT5_C` (clone of B's proven install) |
| Data folder | `%APPDATA%\MetaQuotes\Terminal\71BF6B2AB5548CFBA970FA2F38007C31` |
| Magic | **7788125** (A = 7788075, B = 7788100; 7788125 verified unused) |
| Chart | `MQL5\Profiles\Charts\Default\chart01.chr` — clone of arm A's validated chart, EA `MitemshubAI` on Volatility 75 Index M15, `InpLiveExecution=false` (paper), `InpPaperEquity=50`, TP placeholder 1.8 |
| Credentials | auto-login verified: `authorized '140778269' on DerivSVG-Server-03` (the pointer lives in `config\common.ini` `Login=`/`Server=` — copying `accounts.dat` alone is NOT enough; that cost an hour on 2026-09-05) |
| Build & presets | synced by `sync-mt5.ps1` (75 files, build gate PASS; auto-discovers the folder) |
| Validation launch | 2026-09-05 11:10 UTC: v26.35 banner, FIT ROUTER TOLERATED ($4.65 min-lot risk = 9.3%/trade at $50 virtual), self-check clean, paper equity $50.00 initialized, state + telemetry written |
| Current state | **PARKED — terminal OFF, 2 terminals running (A, B)** |

## The standing rule (from docs/V75_COST_DILUTION_STUDY.md)

Arm C stays OFF until BOTH hold:
1. A study returns **VALIDATED-CANDIDATE** (as of 2026-09-05: zero candidates —
   cost-dilution was NO-ADOPT 5/5; the TP A/B question belongs to arms A/B).
2. The primary A/B (arm A vs arm B) has adjudicated **without contamination**
   from the candidate experiment.

A running arm C before an adoption decision trades an un-adopted config and
mints data nobody reads — parked is the correct default state.

## Activation procedure (minutes, not hours)

1. **Point the chart at the adopted config** (only step that changes per adoption):
   edit `71BF6B2AB5548CFBA970FA2F38007C31\MQL5\Profiles\Charts\Default\chart01.chr`
   (UTF-16): set the adopted `InpTpMult` / any adopted inputs. Keep
   `InpMagic=7788125`, `InpLiveExecution=false`.
2. `powershell -Command "Start-Process -FilePath 'C:\Users\USER\AppData\Local\MitemshubMT5_C\terminal64.exe'"`
   (the Bash `&` background trick hangs the shell — use Start-Process).
3. Verify within ~60s: journal line `authorized '140778269'` in
   `logs\<today>.log`; Experts log `MQL5\Logs\<today>.log` shows the
   `[v26.35]` banner + `FIT ROUTER ... TOLERATED` and `PAPER MODE`; magic
   7788125 appears in telemetry (`fit` event).
4. `python scripts/morning_status.py` must now show **3** terminals / three arms.

## Adding arm C to the tooling (at activation)

- `scripts/morning_status.py`: extend `MAGICS` with `{"C_cand": 7788125}` (one line).
- `scripts/paper_pipeline.discover_arm_dirs()` discovers A/B by magic; the
  candidate's adjudication must be a NEW pre-registered rule (candidate vs
  arm A reference), written before its 30th trade — not an A/B rerun.

## Teardown (if the candidate is rejected)

Delete the data folder `71BF6B2AB5548CFBA970FA2F38007C31` and the install
`%LOCALAPPDATA%\MitemshubMT5_C`. Nothing else references magic 7788125.
