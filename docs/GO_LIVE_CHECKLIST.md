# GO-LIVE CHECKLIST — $50, terminal A, magic 7788075 (written 2026-09-05, rehearsed read-only)

This is the exact procedure to execute when the pre-registered gate passes
(TJ1 paper A/B positive + TJ2 tick reconciliation + TJ3 watchdog — see
`docs/OPERATING_SUMMARY.md`). It was rehearsed read-only on 2026-09-05; every
file and expected string below was verified against the live system. **Do not
execute until the gate says go.**

## Preconditions (all must be true)

- [ ] Gate verdict = GO LIVE (TJ1 + TJ2 + TJ3, from the Sunday pipeline).
- [ ] Real account **140778269** funded ≥ $50. (2026-09-04 record: $0.57 —
      check YOUR broker-side balance; the FIT ROUTER banner at attach is the
      authoritative confirmation. Hard floor $31 — below it every signal is
      vetoed by the broker lot floor, by design.)
- [ ] Terminal A running (`C:\Program Files\MetaTrader 5 Terminal\terminal64.exe`,
      data folder `FB9A56D617EDDDFE29EE54EBEFFE96C1`).
- [ ] Preset in place and validated — `MQL5\Experts\MITEMSHUB_AI\MitemshubAI_VOL75_LIVE.set` (repo source: `mql5/MITEMSHUB_AI/MitemshubAI_VOL75_LIVE.set`)
      **byte-identical to repo** (verify with `python scripts/verify_go_live_artifacts.py`; repository-side identity checked 2026-09-05): `InpLiveExecution=true`,
      `InpMagic=7788075`, `InpTpMult=1.8`, `InpPaperEquity=50.0` (inert in live),
      `InpFleetMagicsCSV=...,7788075,7788100` (A and B both in the account-wide
      fleet guard — both must stay in the CSV; B stays paper).
- [ ] EA build = v26.35 (`MitemshubAI.mq5` + compiled `.ex5` synced; the same
      build that has run paper arms — no unverified build ever goes live first).

## Procedure — terminal A, chart01, V75 M15

1. **Stop the paper EA**: chart01 → right-click EA → Remove (or Delete). Confirm
   the Experts log shows the EA removed. (B stays running — do NOT touch B.)
2. **Re-attach the EA**: drag `MitemshubAI` onto chart01 → in the dialog press
   **Load** → select `MitemshubAI_VOL75_LIVE.set` → **OK**.
3. **Enable Algo Trading** if prompted (MT5 toolbar button / `Ctrl+E`).
4. **Confirm the banner** — the Experts log must contain ALL of:

   | expected line (exact markers) | meaning |
   |---|---|
   | `MITEMSHUB AI v26.35 started ... Standard Mode` | correct build |
   | **NO `PAPER MODE:` line** | the discriminator — live, not paper |
   | `FIT ROUTER: instruments vs a $50.00 account` (or your funded $) | live balance read |
   | `Volatility 75 Index min-lot stop-risk $X.XX ... TOLERATED, each trade risks Y.Y% of equity` | sizing fits at $50 (expect X ≈ 4.5–6.5, Y ≈ 9–13% depending on current ATR) |
   | `RiskCap=20%` line + `WARNING: risk cap > 10% — tiny-account mode.` | expected at $50, not an error |
   | `[SELFTEST] ... OK`, `GARCH ready`, `Telemetry -> ...`, `State -> ...` | engine initialized |

5. **Confirm magic + TP on the chart**: input tab (F7) shows `InpMagic=7788075`,
   `InpTpMult=1.8`, `InpLiveExecution=true`. Dashboard **MODE shows `LIVE`**.
6. **Do NOT modify any input** by hand. The preset IS the config.

## First-trade confirmations (within the first signals)

- Journal shows real order lines: `Executing BUY vol=0.01 SL=... TP=... | <reason>`
  (or SELL) — this is the live path (`trade.Buy/Sell`), and the position appears
  in the terminal's Trade tab with magic 7788075.
- Any `SKIP ... min-lot risk $X exceeds cap $Y (Z% equity)` lines are the governor
  vetoing — expected and correct (not errors).
- Any `ORDER FAILED retcode=...` → **STOP** (see abort).

## $50 truth table (what to expect and why it's OK)

| account | min-lot stop-risk (today's ATR) | per trade | verdict |
|---|---|---|---|
| **$50 (live)** | ≈ $4.6–6.5 | ≈ 9–13% of equity | TOLERATED — trades, sharply. This is the pre-registered minimum-viable size. |
| $31 (floor) | ≈ $4.6–6.5 | ≈ 20% (the cap) | TOLERATED at cap — absolute floor, not a target |
| < $31 | same $ | > 20% | `CANNOT FIT` — every signal vetoed. Fund or don't attach. |
| $100+ | same $ | ≈ 5–7% | the sane size for later compounding |

Model: long-run cost-inclusive expectancy ≈ +0.038R/trade (net, certified window,
t=0.35) → at 0.01 lots ≈ +$0.20/trade expected; the account grows by surviving
and compounding ~2 trades/day, not by heroics. Risk is the constraining resource.

## Abort criteria (any one → stop immediately, investigate, do not trade)

- Banner contains `PAPER MODE:` (the LIVE set did not load — load failed silently).
- `FIT ROUTER ... CANNOT FIT` at your funded balance (account < floor → fund it).
- `InpMagic != 7788075` or `InpTpMult != 1.8` on the chart after load.
- Dashboard MODE is not `LIVE`.
- Any `ORDER FAILED` retcode (network/broker issue → check, don't retry blindly).
- First live fill symbol ≠ Volatility 75 Index, or magic != 7788075 in the Trade tab.

## After attach — steady state

- Keep running `python scripts/morning_status.py --strict` daily (arms, gaps,
  gate X/30 — now also shows the live arm).
- Compare live fills vs the paper ledger: **the same signals should print in both**
  — any divergence means the live attach drifted from the preset; stop and re-run
  the checklist.
- B keeps paper-testing TP 2.4 until the A/B duel finishes, then is parked.
- Withdraw weekly everything above a $100 working buffer (funding plan) — never
  drain below the $50 live floor.