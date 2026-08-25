# MitemshubAI v22 — Strategy Tester Validation Protocol

## Band-fade leg on Volatility 75 / Volatility 100 · 6 months of M15

**Goal:** prove (or kill) the band-fade edge under real MT5 execution mechanics — spread,
intrabar path resolution, tight-stop fills — before any more live money touches it.

**Configs:** `MitemshubAI_TESTER_BFONLY_VOL100.set` / `..._VOL75.set` (isolation rigs:
band-fade only, breakers neutralized, trailing & breakeven OFF → measures PURE sigma
geometry). Deploy configs stay untouched: `*_FINAL.set`.

---

## Tester panel settings (both passes)

| Setting | Value | Why |
|---|---|---|
| Expert | `MitemshubAI` (v22 build) | — |
| Symbol (run 1) | **Volatility 100 Index** | VERIFIED live via scripts/mt5_probe.py |
| Symbol (run 2) | **Volatility 75 Index** | VERIFIED; run separately, never blended |
| Period / Timeframe | **M15** | EA also enforces M15 entry / H1 regime via overrides |
| Date range | **2026.02.25 → 2026.08.25** | 6 months; synthetics trade 24/7 so weekends count |
| Modelling | **"Every tick based on real ticks"** if available, else **"1 Minute OHLC"** | stop = 0.10×σ_h ≈ 0.05–0.08% of price on M15 — "Open prices only" would fabricate fills and invalidate the test |
| Deposit | Pass A: **10,000 USD** · Pass B: **30 USD** | see passes below |
| Leverage | 1:100 (any) | sizing is risk-based; leverage is near-irrelevant |
| Optimization | **Disabled** (A, B) · enabled only in C | fixed params = honest validation |
| Forward | Off | nothing is being optimized |
| Visual mode | Off | speed |

Load inputs: **Inputs tab → right-click → Load → select the `_TESTER_BFONLY_*.set` file.**

---

## The three passes

### Pass A — Raw edge (per symbol)
- Config: `_TESTER_BFONLY_VOL100.set` / `_TESTER_BFONLY_VOL75.set`, deposit $10,000.
- Breakers/cap neutralized and trailing off on purpose: we are measuring the *leg's*
  geometry, not the risk system (already audited).
- Record: trades, PF, expectancy R/trade, max DD in R, exit-reason split
  (TARGET/STOP/TIME), monthly P&L.

### Pass B — Realism at live size (per symbol)
- Same runs but load the **deployed** `MitemshubAI_VOL100_FINAL.set` /
  `_VOL75_FINAL.set`, deposit **$30**, every-tick modelling.
- No pass/fail: counts how many valid band-fade signals survive the min-lot risk cap,
  daily-loss halt and consec-loss pause at real account size. This number decides how
  much funding the strategy needs — not whether the edge exists.

### Pass C — Parameter robustness sweep (Volatility 100 only, optional but recommended)
- Optimization: genetic disabled, grid over two parameters (9 runs):
  - `InpBandZEntry` ∈ {1.7, 2.0, 2.3}
  - `InpBandTargetSigmaMult` ∈ {0.64, 0.80, 0.96}
  (`InpBandStopSigmaMult` stays 0.10.)
- An edge that only lives at one cell is curve-fit noise.

---

## Pass criteria (Pass A, applied per symbol)

| # | Gate | Threshold | If failed |
|---|---|---|---|
| 1 | Sample size | ≥ 30 trades | extend history or loosen z — verdict is *insufficient data*, NOT failure |
| 2 | Profit Factor | ≥ 1.30 | kill or redesign leg |
| 3 | Expectancy | ≥ +0.15 R/trade | same |
| 4 | Max drawdown | ≤ 12 R | tighten gates before promoting |
| 5 | TIME-exit share | ≤ 40% of exits | hold horizon misfit — investigate, don't promote blindly |
| 6 | Spread stress (rerun with ~2× spread) | PF ≥ 1.10 | tight stops too fragile for real spreads |

Note on win rate: geometry is RR≈8:1 (target 0.80σ_h vs stop 0.10σ_h) → breakeven WR ≈
11%. Low WR alone means nothing here; PF and expectancy decide.

**Robustness (Pass C):** PF ≥ 1.05 in ≥ 7 of 9 cells.
**Promotion rule:** both symbols pass primary gates → forward-demo scoreboard;
one symbol passes → trade that symbol only; none pass → back to research. Do NOT
loosen gates to manufacture trade frequency.

---

## After each run — send back for analysis

1. The tester report (save as HTML/Open XML) from every pass.
2. The telemetry journal the EA writes during tests:
   `<TerminalData>\Tester\<agent>\MQL5\Files\MitemshubAI_v22_telemetry.jsonl`
   (exact agent path is printed in the Journal tab when the test starts).
3. From `sig` events I can report gate hit rates on 6 months of data: bars with
   z≥2 vs expansion-passed vs BOTH-passed — i.e., measured selectivity and where
   frequency actually leaks.

---

## Known limitations

- Tester fills are still optimistic vs live slippage on a fast fade; the spread-stress
  rerun partially compensates.
- 6 months × M15 gives maybe 40–120 band-fade fires per symbol; treat sub-gate-1 results
  as "keep collecting", not as proof either way.
- Pass A uses fixed fractional sizing at 0.5% risk — compounding differs from the $30
  account's forced min-lot behavior (that's what Pass B quantifies).
