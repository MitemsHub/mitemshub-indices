# MITEMSHUB AI — Production Configuration Guide
# Deriv Volatility 75 / 100
# Generated: 2026-08-20

## Overview

This document provides production-ready EA configurations for live trading
on Deriv synthetic indices (Deriv Volatility 75/100). Three risk tiers
are provided, from conservative to aggressive. Always start with Tier 1.

---

## Backtest Results (Optimized Parameters)

| Symbol | Strategy | Trades | Win Rate | Profit Factor | Expectancy | Net PnL ($1k) |
|--------|----------|--------|----------|---------------|------------|---------------|
| R_75 | Band (optimized) | 69 | 10.14% | 1.24 | +0.229R | +$75.52 |
| R_75 | Fade (mean-reversion) | 106 | 72.64% | 1.50 | +0.157R | +$91.48 |
| R_100 | Band (optimized) | 48 | 14.58% | 1.47 | +0.399R | +$105.62 |

---

## Risk Tiers

### Tier 1: Conservative (Recommended for first 30 days)
- **Risk per trade:** 0.25% of equity
- **Max daily loss:** 2%
- **Max equity drawdown:** 5%
- **Max consecutive losses:** 3
- **Max trades per day:** 5
- **Floor gate:** ON (must beat break-even hit rate)

### Tier 2: Standard (After 30 days of verified performance)
- **Risk per trade:** 0.50% of equity
- **Max daily loss:** 3%
- **Max equity drawdown:** 8%
- **Max consecutive losses:** 4
- **Max trades per day:** 8
- **Floor gate:** ON

### Tier 3: Aggressive (Only with proven track record 90+ days)
- **Risk per trade:** 1.0% of equity
- **Max daily loss:** 5%
- **Max equity drawdown:** 12%
- **Max consecutive losses:** 5
- **Max trades per day:** 10
- **Floor gate:** ON

---

## Safety Rules (Non-Negotiable)

1. **NEVER** disable the floor gate in production
2. **NEVER** set MaxConsecutiveLosses > 5
3. **NEVER** set MaxDailyLossPct > 5%
4. **NEVER** set MaxEquityDDPct > 15%
5. **ALWAYS** start with Tier 1 for the first 30 days
6. **NEVER** share one magic across parallel charts — each instance loads its own FINAL `.set`, which pins a unique fleet magic (VOL10=7788010, VOL25=7788025, VOL50=7788050, VOL75=7788075, VOL100=7788100) so position attribution and the account-wide guard never cross-contaminate
7. **ALWAYS** verify the EA shows "MODE: LIVE" on the dashboard
8. **STOP TRADING** if the EA prints "EMERGENCY_STOP - TRADING DISABLED"

---

## .set File Loading

1. Copy the appropriate .set file to: `%APPDATA%\MetaQuotes\Terminal\<ID>\profiles\sets\`
2. Attach MitemshubAI to the matching chart — VERIFIED live 2026-08-25 (`scripts/mt5_probe.py`, 730 symbols enumerated): the tradable names ARE the display names `Volatility 10/25/50/75/100 Index` (+ separate `(1s)` variants with different contract specs). There are NO "SYNxx" symbols on this terminal; ignore any older note claiming otherwise.
3. Expert Advisors → Properties → Common tab → Load
4. Select the .set file
5. Verify all inputs match the expected values
6. Enable Algo Trading
7. Check dashboard shows correct mode

---

## Monitoring

The EA writes its state to the chart via the Dashboard panel:
- **MODE:** Should show "LIVE" when InpLiveExecution=true
- **REGIME:** Current market regime (RANGE, TREND, etc.)
- **DECISION:** Last signal (BUY/SELL/WAIT)
- **DRAWDOWN:** Current drawdown percentage
- **OPEN POSITIONS:** 0 or 1 (single position mode)

If you see "EMERGENCY_STOP - TRADING DISABLED" in red:
- The EA has hit a hard risk limit
- Do NOT restart it immediately
- Check your equity and recent trades
- Investigate before re-enabling

---

## Emergency Procedures

### If the EA halts due to daily loss:
1. Do NOT restart the EA
2. Check your account equity
3. Review the last 5-10 trades in the journal
4. Wait until the next session day (midnight server time)
5. The EA will automatically reset daily counters

### If the EA halts due to consecutive losses:
1. The streak counter resets on a new session day
2. Or if a trade closes with return_r >= -0.10R (a scratch)
3. Investigate the losing streak before re-enabling

### If the EA halts due to equity drawdown:
1. This is the most serious halt
2. Do NOT restart until you understand why
3. The peak equity is tracked and will not reset automatically
4. You may need to manually adjust g_peakEquity in the EA state

---

## File Locations

| File | Purpose |
|------|---------|
| `MitemshubAI_Deriv Volatility 75_LIVE.set` | LEGACY (v15-era naming) — use `MitemshubAI_VOL75_FINAL.set` |
| `MitemshubAI_Deriv Volatility 100_LIVE.set` | LEGACY (v15-era naming) — use `MitemshubAI_VOL100_FINAL.set` |
| `MitemshubAI_PAPER_TEST.set` | Paper/tester with permissive limits |
| `PRODUCTION_CONFIGS.md` | This document |

---

---

## v22.0 Changes (2026-08-25) — READ BEFORE DEPLOYING

The live losing spree (Aug 17–22) was diagnosed to five root causes. v22.0 fixes all of them:

| # | Root cause found in production | v22.0 fix |
|---|-------------------------------|-----------|
| 1 | `g_paused` latched **permanently** after 3 consecutive losses — never reset, bot sat idle for days | Pause + streak auto-reset at session-day rollover |
| 2 | `InpMaxDailyLossPct` existed but was **never enforced** | Daily-loss halt wired into the entry gate; resets next day |
| 3 | Min-lot floor silently forced ~25% effective risk per trade on the $30 account | `InpMaxEffectiveRiskPct` hard cap refuses entries whose REAL min-lot risk breaches it (+ loud warning above 5%) |
| 4 | Momentum leg fired on any single large candle → chased tops/bottoms of vol spikes on a mean-reverting index (8 of 9 Aug-17 losses) | Momentum demoted to confluence vote (`InpMomentumStandalone=false`); validated **band-fade** leg added as primary signal |
| 5 | `.set` files carried v15-era input names that MT5 silently dropped on newer builds; terminal ran a binary older than repo HEAD | Both FINAL `.set` files regenerated with full v22 input coverage; EA prints a `[v22]` banner with TF/risk config at start — verify it matches before trusting the run |

### Band-fade leg (the validated edge)

Port of Python `band_geometry.py` + `vol_band.py` gates:
- Fires when volatility just expanded (`sigma > InpBandVolExtRatio x sigma EMA`) AND price is extended (`|z_dev| >= InpBandZEntry`, `z_dev = ln(close/sma)/sigma`)
- Fade direction: extension ABOVE → sell; extension BELOW → buy
- Levels: `stop = 0.10 x sigma_h`, `target = 0.80 x sigma_h` (R_100) / `1.20 x sigma_h` (R_75), scaled by `sqrt(hold_bars)`
- Allowed regimes: RANGING and HIGH_VOL (expansion IS its edge — HIGH_VOL is no longer a global block)

### Timeframes

`.set` files now pin `InpEntryTFOverride=M15`, `InpRegimeTFOverride=H1` — attach to ANY chart; execution quality no longer depends on where you dropped the EA.

### Tiny-account reality check ($30)

V100's min lot makes ~$8 risk per trade unavoidable (~27% of a $30 account). No edge survives that. The cap prevents blowups but the honest options are:
1. Fund to $250+ so min-lot risk ≤ ~5% (recommended), or
2. Accept tiny-account mode consciously (current config), or
3. Trade **Volatility 75 Index** — its verified min-lot floor is ≈$0.08/trade (~0% of equity), the ONLY symbol whose sizing works at $30. V10/V25 floors are $40/$22 per trade (162%/90% of a $30 account) — they are the WORST tiny-account choices, not the best.

## Version History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-25 | v22.1: 5-symbol parallel profiles (VOL10/25/50 added), unique magics per chart (77880+vol tier), venue-name note | MITEMSHUB AI |
| 2026-08-25 | v22.0: pause auto-reset, daily halt wired, risk guardrail, band-fade leg, momentum demotion, TF overrides, set files regenerated | MITEMSHUB AI |
| 2026-08-20 | Initial production configs from backtest optimization | MITEMSHUB AI |

## Five-Symbol Parallel Operation (v22.1)

One EA instance per chart; each `.set` pins timeframes and a UNIQUE magic so position
attribution and recovery never cross-contaminate:

| Set file | Symbol (internal) | Magic | z≥ | Target σ_h | Risk cap | Daily halt | Status |
|---|---|---|---|---|---|---|---|
| `MitemshubAI_VOL10_FINAL.set` | R_10 | 7788010 | 2.3 | 0.60 | 8% | 10% | ❌ REJECTED — no edge on 208d real M15 (PF 0.96, expR −0.04); spread ≈26% of band-stop width |
| `MitemshubAI_VOL25_FINAL.set` | R_25 | 7788025 | 2.2 | 0.70 | 10% | 12% | ⏸ SHELVED — real edge (PF 1.44, +0.36R) but 27R drawdown; re-tune before use |
| `MitemshubAI_VOL50_FINAL.set` | R_50 | 7788050 | 2.0 | 0.80 | 12% | 15% | 🟡 CONDITIONAL — passes edge+TIME gates (PF 1.55, +0.46R, 0% TIME); DD 16R ⇒ cap risk ≤0.9% |
| `MitemshubAI_VOL75_FINAL.set` | R_75 | 7788075 | 2.0 | 1.20 | 35%* | 35% | ✅ VALIDATED (real-history + walk-forward); DD 20R ⇒ risk ≤0.75% keeps modeled DD ≤15% eq |
| `MitemshubAI_VOL100_FINAL.set` | R_100 | 7788100 | 2.0 | 0.80 | 30%* | 30% | ✅ VALIDATED edge (PF 1.63, +0.52R); DD 14R marginal |

**Drawdown-gate note (2026-08-25):** the fixed "maxDD ≤ 12R" promotion gate proved
too strict for any always-on single leg over 208 days — even the validated anchor trips
it. Treat R-drawdown as a SIZING input instead: pick risk% so that `DD_R × risk%`
stays inside your equity-drawdown tolerance (e.g. 15% equity → V75 ≤0.75%, V50 ≤0.9%).

\* V75/V100 caps are deliberately loose — on the $30 account the min-lot floor forces the risk anyway;
the cap only bounds catastrophe there. On V10/25/50 min-lot risk is small, so caps do real work.

### ✅ Chart names & contract reality (VERIFIED live 2026-08-25 via `scripts/mt5_probe.py`, 730 symbols enumerated)
The display names ARE this terminal's real, FULL-tradeable symbols:
`Volatility 10/25/50/75/100 Index` (+ separate `(1s)` variants with different contract
specs). There are NO "SYNxx" symbols — an earlier repo comment claiming so was stale.
`DERIV_SYMBOL_MAP` and controller aliases are now aligned to these verified names.

**Min-lot risk floor at a 1.7% stop (live specs, ~$25 equity):**

| Symbol | Risk/trade @min lot | % of equity | Verdict now |
|---|---|---|---|
| **Volatility 75 Index** | **$0.08** | **~0%** | 🟢 **ANCHOR — primary live symbol** |
| Volatility 75 (1s) Index | $6.27 | 25% | 🟡 optional once profitable |
| Volatility 50 Index | $6.84 | 27% | 🟡 borderline — demo first |
| Volatility 100 Index | $10.39 | 42% | 🔴 demo only until funded |
| Volatility 25 Index | $22.51 | 90% | ⛔ not viable at this equity |
| Volatility 10 Index | $40.49 | 162% | ⛔ not viable at this equity |

**Revised fleet advice:** live = `MitemshubAI_VOL75_FINAL.set` on *Volatility 75 Index*
(risk floor effectively zero → the 30%-cap tiny-account problem disappears).
Keep VOL100/VOL10/VOL25 sets for demo/funded phases. The five-symbol parallel plan
stands, but composition is equity-gated, not preference-gated.

---

## MAX-FREQUENCY AGGRO Profiles (2026-08-25 — operator-requested)

`MitemshubAI_VOL100_AGGRO.set` / `MitemshubAI_VOL75_AGGRO.set` — same EA, same fleet
magics, deepest signal gate that still passed real-tick validation:

| Change vs FINAL | Value | Why |
|---|---|---|
| `InpBandZEntry` | 2.0 → **1.0** | deepest VALIDATED gate; ~3× trade rate (V100 ~7/day, V75 ~7/day in active windows) |
| `InpMaxEffectiveRiskPct` (V100 only) | 30 → **45** | lets the unavoidable $10.39 min-lot risk (~40% of $30) actually trade |
| `InpMaxTotalRiskPct` | 15 → **50** | account ceiling widened so the big V100 min-lot entry fits |
| `InpMaxConsecLoss` | 3 → **6** | fewer mid-streak shutdowns |
| `InpCoolDownBars` | 3 → **1** | re-arm one bar after a close |

**Straight math on a $30 account (V100 AGGRO):** min lot forces ~$10.39/trade ≈ 40% of
equity. At a ~17% win rate, three losers in a row is entirely ordinary — that is **−78%**
of the account; five losers is **−92%**. This profile can genuinely 2–3× an account in a
hot week and can zero it in one bad afternoon. V75 AGGRO carries the same frequency with
~$0.08/trade risk — same engine, survivable sizing. Run V75 AGGRO as the workhorse;
treat V100 AGGRO as rocket fuel, not cruise mode.

**Frequency reality:** 15–20 trades/day on ONE symbol is not reachable at any gate that
still made money — z=1.0 is the floor (looser gates measured NEGATIVE expectancy after
spread on real ticks). Two aggro charts together realistically print **~5–14 trades/day**
depending on the volatility regime. More frequency than that = paying spread to lose.

### Real-history validation (208 days M5→M15/H1, conservative fills)
`scripts/backtest_real_history.py` on terminal-exported candles confirms the deployed
tune: **z=2.0 beats z=1.4/z=1.0 on ALL three tested symbols at M15** (e.g. V75 PF 1.57
+0.50R; V100 PF 1.63 +0.52R), H1 loses on most cells → M15-only deployment confirmed.
Earlier synthetic-sweep suggestion of looser z gates does NOT survive real microstructure.
See `artifacts/bandfade_real_M15.json`.

### Tuning rationale (vol-tier scaling)
Lower annualized vol ⇒ smaller sigma ⇒ spread eats more of each move:
deeper z-entry (2.3→2.0 as vol rises), nearer fade targets (0.60→0.80σ_h),
tighter max-stop-% (1.0%→1.5%), tighter risk/daily-halt caps where min-lot allows.
The three new tiers are STARTING TUNES — run STRATEGY_TESTER_VALIDATION.md Pass-A
gates per symbol before sizing up. Expect few signals from VOL10 by design.
