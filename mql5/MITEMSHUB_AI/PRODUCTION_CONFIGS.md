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
6. **ALWAYS** keep the magic number consistent (7788123)
7. **ALWAYS** verify the EA shows "MODE: LIVE" on the dashboard
8. **STOP TRADING** if the EA prints "EMERGENCY_STOP - TRADING DISABLED"

---

## .set File Loading

1. Copy the appropriate .set file to: `%APPDATA%\MetaQuotes\Terminal\<ID>\profiles\sets\`
2. Attach MitemshubAI to Deriv Volatility 75 or Deriv Volatility 100 chart
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
| `MitemshubAI_Deriv Volatility 75_LIVE.set` | Deriv Volatility 75 optimized band parameters |
| `MitemshubAI_Deriv Volatility 100_LIVE.set` | Deriv Volatility 100 optimized band parameters |
| `MitemshubAI_PAPER_TEST.set` | Paper/tester with permissive limits |
| `PRODUCTION_CONFIGS.md` | This document |

---

## Version History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-20 | Initial production configs from backtest optimization | MITEMSHUB AI |
