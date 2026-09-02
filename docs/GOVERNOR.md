# The Governor — Plain-Language Guide (v26.23)

> The governor is the EA's self-management layer: it watches every strategy's
> real results, **benches the losers, keeps the winners, gives benched
> strategies a chance to earn their way back**, and now also coordinates
> *when* and *how well* the engine trades.

## The loop in four steps

**1. Record.** Every closed trade adds one row to its strategy's scorecard:
trades, wins, total R (R = your risk unit; +2R means you made twice your
risk, −1R means the stop was hit).

**2. Review.** Every N trades (strategy review @10, regime @20, time-of-day
@30) the governor checks each strategy that has enough history to judge
(min 15 trades):
- **ExpR** (expectancy) = average R per trade — the only number that decides anything.
- ExpR below the floor (0.10R on Boom/Crash charts, 0.00R on Volatility
  charts) → **DISABLED**.
- ExpR at or above the floor → **KEEP**, or **REINSTATED** if it was benched.

**3. Enforce.** A benched strategy is **blocked from trading** on every trade
path — classic legs, CB bar engine, CB tick-fade, VB burst. (Before v26.20
the "DISABLED" stamp existed but nothing enforced it.)

**4. Probe (no permanent prison).** A benched strategy still takes **every
10th signal** that comes its way, so its scorecard stays alive and a
recovered edge earns automatic reinstatement at the next review. Probe
counters persist across restarts.

## Coordination layer (v26.22–v26.23)

| Feature | Input | What it does |
|---|---|---|
| **Win-rearm** | `InpWinRearm=true` | After a **winning** close the governor re-arms instantly (cooldown = 0) and organises the next entry. After a **loss** the full cooldown breather still applies — re-entry into the move that just stopped us out is how accounts die. |
| **Spread-quality gate** | `InpMaxSpreadATRFrac=0.18` | Before any entry the live spread is measured; if it exceeds **18% of the planned stop distance** the trade is refused (no cooldown charged — the next bar's quote is re-checked). Forensics from the 63-cell scalp sweep: spread was ~44% of the backtest's out-of-sample loss. |
| **Conviction throttle** | `InpAdaptiveConviction=true` | On a **net-negative day** the minimum entry score rises by one (`MinScore + 1`) — fewer, higher-conviction trades while red. A green/flat day restores full access. |

Design note: the geometry itself (stop/TP multipliers, hold cap) is **not**
adapted at runtime. The 63-cell scalp sweep
(`artifacts/scalp_sweep_volatility_75_index.json`) showed every tighter-TP
cell loses out-of-sample on V75 — the data gate rejected scalp-sized targets,
so the governor coordinates *access and quality*, never unvalidated geometry.

## What "Wilson bound" means

A win rate from a few trades **lies**. The **Wilson 95% lower bound** answers:
*"given what I've seen, what's the worst win rate that's statistically
realistic?"* It gets more honest as trades accumulate:

| Record | Naive win rate | Wilson lower bound |
|---|---|---|
| 2 wins / 2 trades | 100% | **34%** |
| 7 / 10 | 70% | **40%** |
| 50 / 100 | 50% | **40%** |
| 70 / 100 | 70% | **60%** |

2/2 and 70/100 both "average" high, but only the 70/100 has earned trust —
its bound (60%) is nearly as high as its average. Reviews and the journal
report `WR=70% (LB 60%)` so a real edge is distinguishable from a lucky
streak. (The kill *decision* uses ExpR — that protects capital immediately;
the bound is for honest visibility.)

## What you'll see

**Dashboard — when everything is healthy**, no governor line, just:
```
Intel: Best=CB-TICKFADE(+8.8R) Worst=CB-GRIND(-2.0R) Reviews:3
Coord: spread-gate ON (18% stop) | conviction normal
```

**Dashboard — when something is benched:**
```
Governor: BF(probe 3/10), CB-GRIND(probe 0/10)
Coord: spread-gate ON (18% stop) | conviction min+1 (day in red)
```
`probe 3/10` = 3 signals came to BF since it was benched; the 1st, 11th,
21st… signal trades so its statistics keep moving.

**Journal — at every strategy review:**
```
STRATEGY PB:   20 trades, WR=65% (LB 43%), ExpR=+0.32 → KEEP
STRATEGY BF:   18 trades, WR=38% (LB 20%), ExpR=-0.21 → DISABLED (below 0.10 R/trade)
STRATEGY CB-FADE: 25 trades, ... → REINSTATED (recovered above floor)
```

**Journal — at startup (v26.23):**
```
Governor v2: enforcement ON; suppressed strategies probe every 10-th signal (probing enabled)
Governor v3 coordination: spread-gate ON (max 18% of stop), conviction throttle ON, win-rearm ON
```

## What the governor is NOT

It manages what trades — it cannot conjure edge. If the signal engine's
blend is net-negative, the governor contains the bleeding, keeps the
statistics honest, and coordinates access; making the engine itself
net-positive is the entry-edge workstream (forward-split backtest protocol,
`scripts/fwd_split_backtest.py`). Two ideas have already been killed by the
data gate rather than by live losses: the Volatility burst-fade module
(70-cell calibration, every configuration negative) and scalp-sized TPs
(63-cell sweep, all OOS-negative). That is the governor philosophy working:
ideas pay for their proof with an afternoon of data, not with the account.
