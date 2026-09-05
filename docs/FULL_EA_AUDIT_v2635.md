# Full EA Code Audit — v26.35 (2026-09-04, pre-live)

Scope: every decision path in `MitemshubAI.mq5` (~3,373 lines) cross-checked
against the certified offline mirror (`certify_v75.py`), all 15 presets, and
both live paper terminals. Method: line-by-line review of init, signal,
sizing, order-send, position management, close handling, persistence, and
file I/O.

## Fixed in v26.35 (were live bugs)

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | **CRITICAL (paper)** | ACCOUNT GUARD in `OpenTrade` used **real account equity** (`AccountInfoDouble`) while sizing used paper virtual equity — with $0.57 real vs $50 paper, `fleet + $6.25 risk > $0.086 cap` vetoed **every paper entry**. This is the root cause of the weeks-long paper silence mystery from the v26.28 era. | Guard now uses `PaperActive() ? PaperEquity() : AccountEquity()` — same basis as sizing. |
| 2 | HIGH (live) | Governor gate `StratEnabledOrProbe(i)` returned **`true` on out-of-range index** — any future slot-index mistake (like the v26.34 VB-BURST `8` bug, which this would have silently allowed) bypasses the governor entirely. | OOB now **denies** (fail-closed). |
| 3 | MEDIUM (live) | Default `InpMagic=7788211` is an **orphan magic** — not in `InpFleetMagicsCSV`, so a default-input attach would be invisible to the fleet-risk guard and the close-detection filters. | Default is now `7788075` (the certified V75 magic, in the fleet CSV). |
| 4 | COSMETIC | Self-test banner `PrintFormat` had **9 specifiers / 6 args** — doubles consumed `%d` slots, printing garbage (`regime 1250694476/5`). | Sums cast to `int`; banner now prints true counters. |
| 5 | CONSISTENCY | Dashboard fleet-guard cap used real equity in paper mode (display-only, but misleading). | Same equity-basis fix as #1. |

## Verified clean (no action needed)

- **Sizing chain** matches the certified offline model exactly: `risk = equity × 0.5%` → volume → min-lot clamp → 0.75^loss scaling → effective-risk ≤ 20% veto → fleet-cap check. `g_eq` refreshes from paper/account equity every bar.
- **Order path**: CTrade with magic/deviation/filling set at init; server-side SL+TP on **every** entry (no naked positions); stops-level validity enforced pre-send; slippage deviation 50 pts; failed sends logged with retcode; ticket-verification loop after send with `ResultOrder()` fallback.
- **Engine-plan opener (`OpenTradeLive`, VB-BURST path)**: entry-abort if price outruns SL/TP during send; micro-fit rescales SL/TP on tiny accounts instead of oversizing; its guardrails use `g_eq` (already correct); duplicate-position check before opening.
- **Exit ladder** equals the certified ladder: BE at +1R, PLOCK 0.5R after 1R high-water, 0.7R trail after 0.8R, early-cut at 6 bars if < −0.4R, 20-bar time exit with winner-extension, hard SL/TP checks first — with the v26.13 stop-validity guard on every modify.
- **Close detection**: event-driven + poll fallback + targeted history query + detached-close recovery; duplicate-close guarded via `g_ticket=0`.
- **Persistence**: state/review/slip files symbol-tagged, terminal-local (no cross-terminal collision); paper equity + dangling position restore verified live (survived the accidental terminal kill on 2026-09-04).
- **Strategy table**: 6 slots, all call sites aligned (VB-BURST = 5), `GetStrategyIndex` guarded, `PostTradeReview` ignores unknown names, self-test proves array addressability before any file write.
- **Presets**: all 15 PASS against the v26.35 source; arm presets carry the certified geometry (TP 1.8/2.4, risk 0.5%, cap 20%, consec-loss pause 3, no daily-halt per user decision).
- **No Crash/Boom remnants** in any live code path (only historical comments).

## Deployment state after the audit

- v26.35 compiled **0 errors / 0 warnings**, synced to 13 instances; both paper terminals auto-restored with correct banners, `TOLERATED` router ($6.31 min-lot risk, 12.6%/trade at $50 virtual), and identical signal evaluation.
- Note: the fleet-guard fix (#1) **changes paper behavior from tonight onward** — entries that were silently vetoed by the $0.57-account bug can now fill. Every pre-fix paper statistic is zero by construction; the A/B clock effectively starts now.

## Residual risks (honest list)

1. **Strategy risk, not code risk**: certified edge is +13.23R/60d with 42% max drawdown at min-lot sizing — losing streaks of 5 are **expected**; this is not a "won't lose ever" system.
2. **Daily-loss halt is OFF** (`InpMaxDailyLossPct=0`, removed by user request 2026-08-30). The consec-loss pause (3 losses) is the only session-level brake. For live, consider re-enabling 3–6%.
3. **20% per-trade risk at ~$31–50 equity** is structural (min-lot floor) — the funding plan's $100 recommendation is the real mitigation.
4. **Slippage**: backtests assume stop fills at price; V75 spikes gap (the EA measures this via SpikeSlip telemetry — watch it live).
5. **One instrument, one broker, one regime stretch** of validation — the paper A/B remains the final gate.
