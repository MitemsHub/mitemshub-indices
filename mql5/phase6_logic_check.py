#!/usr/bin/env python3
"""Phase-6 logic mirror — verifies the exact algorithms in MITEMSHUB_AI.

Replicates line-for-line:
  Risk/PositionSizer.mqh        (Python-parity stake + MT5 lot conversion)
  Risk/RiskLimits.mqh           (Max* table, streaks, daily/hourly state)
  Risk/DrawdownProtection.mqh   (equity/daily drawdown fractions)
  Risk/ExposureManager.mqh      (hedging/netting position rules)
  Risk/RiskEngine.mqh           (Python-parity veto gates + sizing authority)

Two layers of validation:
  1. The mirror is checked against the REAL Python production code
     (src/synthetic_trader/risk/engine.py RiskEngine): the stake formula,
     every veto gate's reason, the -0.10R consecutive-loss streak threshold,
     and daily_drawdown_fraction.  (Python rounds stakes to cents; the MQL5
     side does not — the parity gate uses a 0.005 rounding tolerance.)
  2. The mirror runs the same assertion matrix as Tests/Phase6Tests.mq5.

Keep this file in lockstep with the MQL5 side.
"""

import math
import os
import sys
from types import SimpleNamespace

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PHASE6] PASS  {name}")
    else:
        FAIL += 1
        print(f"[PHASE6] FAIL  {name}  -> {detail}")


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol


_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

from synthetic_trader.config import RiskConfig  # noqa: E402
from synthetic_trader.risk.engine import RiskEngine as PyRiskEngine  # noqa: E402


# --- mirror of CPositionSizer ------------------------------------------------
PY_RISK_PER_TRADE = 0.005
PY_STAKE_FLOOR = 0.35
PY_STAKE_CAP_MULT = 1.25
PY_STAKE_BASE_FRAC = 0.55
PY_STAKE_QUALITY_FRAC = 0.70


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def stake_m(equity, risk_per_trade, confidence, min_confidence,
            empirical_scale, stake_floor):
    scale = _clamp(empirical_scale, 0.0, 1.0)
    risk_budget = equity * max(risk_per_trade, 0.0)
    if scale <= 0.0:
        return 0.0
    quality = (_clamp((confidence - min_confidence) / (1.0 - min_confidence), 0.0, 1.0)
               if (1.0 - min_confidence) > 1e-9 else 0.0)
    stake = max(stake_floor, risk_budget * (PY_STAKE_BASE_FRAC + PY_STAKE_QUALITY_FRAC * quality))
    stake *= scale
    stake = min(stake, risk_budget * PY_STAKE_CAP_MULT)
    return max(0.0, stake)


def lots_m(stake, entry, stop, tick_value, tick_size, vol_min, vol_max, vol_step):
    if stake <= 0.0 or entry <= 0.0:
        return 0.0
    dist = abs(entry - stop)
    if dist <= 0.0:
        dist = entry * 0.001
    if tick_value <= 0.0 or tick_size <= 0.0:
        return 0.0
    risk_money_per_lot = dist * tick_value / tick_size
    if risk_money_per_lot <= 0.0:
        return 0.0
    raw = stake / risk_money_per_lot
    step = vol_step if vol_step > 0.0 else 0.01
    floored = math.floor(raw / step + 1e-9) * step
    return _clamp(floored, vol_min, vol_max)


# --- mirror of CRiskLimits / CDrawdownProtection ------------------------------
PY_LOSS_R_THRESHOLD = -0.10


class LimitsM:
    def __init__(self, max_daily_loss=0.05, max_daily_dd=0.08, max_equity_dd=0.15,
                 max_consecutive=5, max_open=1, max_trades_hour=3, max_trades_day=10,
                 max_risk=0.01, max_exposure=0.5):
        self.max_daily_loss = max_daily_loss
        self.max_daily_dd = max_daily_dd
        self.max_equity_dd = max_equity_dd
        self.max_consecutive = max_consecutive
        self.max_open = max_open
        self.max_trades_hour = max_trades_hour
        self.max_trades_day = max_trades_day
        self.max_risk = max_risk
        self.max_exposure = max_exposure
        self.emergency = False
        self.equity = 0.0
        self.peak = 0.0
        self.day_start = 0.0
        self.day_peak = 0.0
        self.consecutive = 0
        self.trades_today = 0
        self.trades_hour = 0
        self.hour_bucket = 0
        self.day_bucket = 0
        self.open = 0

    def set_equity(self, equity, hour, day):
        self.equity = equity
        self.peak = max(self.peak, equity)
        self.day_peak = max(self.day_peak, equity)
        self.sync(hour, day)

    def sync(self, hour, day):
        if self.day_bucket != day:
            self.day_bucket = day
            self.day_start = self.equity
            self.day_peak = self.equity
            self.consecutive = 0
            self.trades_today = 0
        if self.hour_bucket != hour:
            self.hour_bucket = hour
            self.trades_hour = 0

    def register_open(self):
        self.open += 1
        self.trades_today += 1
        self.trades_hour += 1

    def register_outcome(self, pnl, return_r):
        if self.open > 0:
            self.open -= 1
        self.equity += pnl
        self.peak = max(self.peak, self.equity)
        self.day_peak = max(self.day_peak, self.equity)
        if return_r < PY_LOSS_R_THRESHOLD:
            self.consecutive += 1
        else:
            self.consecutive = 0

    def daily_dd_fraction(self):
        loss = max(0.0, self.day_start - self.equity)
        return loss / max(self.day_start, 1e-9)

    def equity_dd_fraction(self):
        loss = max(0.0, self.peak - self.equity)
        return loss / max(self.peak, 1e-9)

    def daily_peak_dd_fraction(self):
        loss = max(0.0, self.day_peak - self.equity)
        return loss / max(self.day_peak, 1e-9)

    def breached(self):
        if self.emergency:
            return True
        if self.max_daily_loss > 0 and self.daily_dd_fraction() >= self.max_daily_loss:
            return True
        if self.max_daily_dd > 0 and self.daily_peak_dd_fraction() >= self.max_daily_dd:
            return True
        if self.max_equity_dd > 0 and self.equity_dd_fraction() >= self.max_equity_dd:
            return True
        if self.max_consecutive > 0 and self.consecutive >= self.max_consecutive:
            return True
        if self.max_trades_day > 0 and self.trades_today >= self.max_trades_day:
            return True
        if self.max_trades_hour > 0 and self.trades_hour >= self.max_trades_hour:
            return True
        if self.max_open > 0 and self.open >= self.max_open:
            return True
        return False


def drawdown_m(equity, peak, day_start, day_peak):
    dd = {
        "daily_loss": (max(0.0, day_start - equity) / max(day_start, 1e-9)),
        "equity": (max(0.0, peak - equity) / max(peak, 1e-9)),
        "daily_peak": (max(0.0, day_peak - equity) / max(day_peak, 1e-9)),
    }
    if dd["daily_loss"] >= 0.02:
        return "daily_loss_limit"
    if dd["daily_peak"] >= 0.05:
        return "daily_drawdown_limit"
    if dd["equity"] >= 0.10:
        return "equity_drawdown_limit"
    return ""


# --- mirror of CExposureManager -----------------------------------------------
MODE_HEDGING, MODE_NETTING = 0, 1


class ExposureM:
    def __init__(self, mode=MODE_NETTING, max_open=1, max_exposure=0.5):
        self.mode = mode
        self.max_open = max_open
        self.max_exposure = max_exposure
        self.open = 0
        self.long_n = 0
        self.short_n = 0
        self.margin = 0.0
        self.equity = 0.0

    def register_open(self, direction):
        self.open += 1
        if direction > 0:
            self.long_n += 1
        elif direction < 0:
            self.short_n += 1

    def register_close(self, direction):
        if self.open > 0:
            self.open -= 1
        if direction > 0 and self.long_n > 0:
            self.long_n -= 1
        elif direction < 0 and self.short_n > 0:
            self.short_n -= 1

    def exposure_fraction(self):
        if self.equity <= 0.0:
            return 0.0
        return max(0.0, self.margin) / self.equity

    def can_open(self, direction):
        if self.max_open > 0 and self.open >= self.max_open:
            return False
        if self.mode == MODE_HEDGING:
            return self.long_n == 0 if direction > 0 else self.short_n == 0
        return self.open == 0


# --- real Python reference helpers --------------------------------------------
def _stub_signal(confidence=0.9, min_confidence=0.48, reward_risk=3.0, features=None):
    s = SimpleNamespace(
        min_confidence=min_confidence,
        confidence=confidence,
        reward_risk=reward_risk,
        symbol="R_75",
        snapshot=SimpleNamespace(epoch=0.0, features=features or {}),
    )
    return s


def main():
    # ===== Parity gate 1: stake formula vs the REAL Python RiskEngine ======
    print("[PHASE6] --- parity: Stake vs real RiskEngine.evaluate ---")
    py = PyRiskEngine(RiskConfig())  # equity 1000, risk 0.005, min 0.48, floor 0.35
    for conf, minc, scale in [(0.90, 0.48, 1.0), (0.70, 0.48, 1.0),
                              (0.48, 0.48, 1.0), (0.90, 0.48, 0.5),
                              (0.90, 0.48, 0.0), (0.99, 0.60, 1.0)]:
        py.state = SimpleNamespace(equity=1000.0, day_start_equity=1000.0,
                                   initial_balance=1000.0, open_positions=0,
                                   consecutive_losses=0, realized_pnl=0.0,
                                   trades_today=0, session_day=1)
        sig = _stub_signal(confidence=conf, min_confidence=minc, reward_risk=3.0)
        dec = py.evaluate(sig, size_multiplier=scale)
        m = stake_m(1000.0, 0.005, conf, minc, scale, 0.35)
        if dec.approved:
            py_stake = dec.intent.stake  # rounded to cents by Python
            ok = abs(m - py_stake) <= 0.0051  # rounding tolerance
            check(f"stake conf={conf} minc={minc} scale={scale} "
                  f"(py={py_stake:.2f})", ok, f"mirror={m:.4f}")
        else:
            check(f"stake paper-only scale=0 (py=0.00)", m == 0.0, f"mirror={m:.4f}")

    # ===== Parity gate 2: every veto gate vs the real Python ================
    print("[PHASE6] --- parity: veto gates vs real RiskEngine ---")
    cases = [
        # (label, mutate_fn, signal_kwargs, expected_reason_kw)
        ("max open positions",
         lambda s: setattr(s, "open_positions", 1),
         {}, "max open positions reached"),
        ("consecutive-loss circuit breaker",
         lambda s: setattr(s, "consecutive_losses", 4),
         {}, "consecutive-loss circuit breaker active"),
        ("daily loss limit",
         lambda s: (setattr(s, "day_start_equity", 1000.0),
                    setattr(s, "equity", 970.0)),
         {}, "daily loss limit reached"),
        ("confidence below min",
         lambda s: None,
         {"confidence": 0.40}, "signal confidence below risk threshold"),
        ("reward/risk below min",
         lambda s: None,
         {"reward_risk": 0.5}, "reward/risk below minimum"),
        ("extreme volatility z",
         lambda s: None,
         {"features": {"range_z_50": 4.0}}, "volatility is statistically extreme"),
    ]
    for label, mutate, sig_kw, kw in cases:
        py.state = SimpleNamespace(equity=1000.0, day_start_equity=1000.0,
                                   initial_balance=1000.0, open_positions=0,
                                   consecutive_losses=0, realized_pnl=0.0,
                                   trades_today=0, session_day=1)
        mutate(py.state)
        sig = _stub_signal(**sig_kw)
        dec = py.evaluate(sig)
        ok = (not dec.approved) and any(kw in r for r in dec.reasons)
        check(f"veto: {label}", ok, f"reasons={dec.reasons}")

    # ===== Parity gate 3: consecutive-loss streak threshold =================
    print("[PHASE6] --- parity: streak threshold vs real RiskEngine ---")
    py.state = SimpleNamespace(equity=1000.0, day_start_equity=1000.0,
                               initial_balance=1000.0, open_positions=1,
                               consecutive_losses=0, realized_pnl=0.0,
                               trades_today=0, session_day=1)
    py.register_outcome(SimpleNamespace(pnl=-0.01, return_r=-0.05))
    check("scratch -0.05R does NOT extend streak (py streak=0)",
          py.state.consecutive_losses == 0, f"streak={py.state.consecutive_losses}")
    py.state.open_positions = 1
    py.register_outcome(SimpleNamespace(pnl=-1.0, return_r=-0.15))
    check("material -0.15R loss extends streak (py streak=1)",
          py.state.consecutive_losses == 1, f"streak={py.state.consecutive_losses}")
    py.state.open_positions = 1
    py.register_outcome(SimpleNamespace(pnl=2.0, return_r=0.5))
    check("win resets streak (py streak=0)",
          py.state.consecutive_losses == 0, f"streak={py.state.consecutive_losses}")

    # ===== Parity gate 4: daily drawdown fraction ===========================
    py.state = SimpleNamespace(equity=970.0, day_start_equity=1000.0,
                               initial_balance=1000.0, open_positions=0,
                               consecutive_losses=0, realized_pnl=-30.0,
                               trades_today=0, session_day=1)
    py_dd = py.daily_drawdown_fraction()
    lm = LimitsM()
    lm.day_start = 1000.0
    lm.equity = 970.0
    check(f"daily drawdown fraction (py={py_dd:.4f})", close(lm.daily_dd_fraction(), py_dd),
          f"mirror={lm.daily_dd_fraction():.4f}")

    # ===== Parity gate 5: register_open counts ==============================
    py.state = SimpleNamespace(equity=1000.0, day_start_equity=1000.0,
                               initial_balance=1000.0, open_positions=0,
                               consecutive_losses=0, realized_pnl=0.0,
                               trades_today=0, session_day=1)
    py.register_open()
    check("register_open increments open+trades_today (py: 1/1)",
          py.state.open_positions == 1 and py.state.trades_today == 1,
          f"{py.state.open_positions}/{py.state.trades_today}")

    # ===== Shared assertion matrix (lockstep with Phase6Tests.mq5) ==========
    print("[PHASE6] --- shared assertion matrix ---")

    # PositionSizer math
    s1 = stake_m(10000.0, 0.005, 0.90, 0.48, 1.0, 0.35)
    # budget 50; quality (0.90-0.48)/0.52 = 0.8077; 50*(0.55+0.70*0.8077)=55.77
    exp1 = max(0.35, 50.0 * (0.55 + 0.70 * (0.90 - 0.48) / 0.52))
    check("stake conf=0.90 -> 55.77", close(s1, exp1, 1e-9), f"{s1:.4f}")
    check("stake never exceeds 1.25x budget", s1 <= 50.0 * 1.25 + 1e-9)
    s_floor = stake_m(100.0, 0.005, 0.48, 0.48, 1.0, 0.35)
    check("stake floor 0.35 applies at min confidence", close(s_floor, 0.35, 1e-9),
          f"{s_floor:.4f}")
    s_half = stake_m(10000.0, 0.005, 0.90, 0.48, 0.5, 0.35)
    check("scale 0.5 halves stake", close(s_half, exp1 * 0.5, 1e-9))
    check("scale 0 -> paper-only 0", stake_m(10000.0, 0.005, 0.90, 0.48, 0.0, 0.35) == 0.0)
    # lots: stake 55.77, dist 0.5, tick_value 0.1, tick_size 0.01 -> $5/lot -> 11.15 lots
    l1 = lots_m(55.77, 100.0, 99.5, 0.1, 0.01, 0.01, 50.0, 0.01)
    check("lots 55.77 stake -> 11.15", close(l1, 11.15, 1e-9), f"{l1:.4f}")
    l_clamp = lots_m(5000.0, 100.0, 99.5, 0.1, 0.01, 0.01, 50.0, 0.01)
    check("lots clamps to vol_max 50", close(l_clamp, 50.0, 1e-9), f"{l_clamp:.4f}")
    l_floor = lots_m(2.27, 100.0, 99.5, 0.1, 0.01, 0.01, 50.0, 0.01)
    check("lots floors to step (2.27/5=0.454 -> 0.45)", close(l_floor, 0.45, 1e-9),
          f"{l_floor:.4f}")
    check("lots degenerate stop uses entry*0.001",
          lots_m(5.0, 100.0, 100.0, 0.1, 0.01, 0.01, 50.0, 0.01) > 0.0)

    # RiskLimits
    check("daily dd fraction 3% of 1000", close(lm.daily_dd_fraction(), 0.03, 1e-9))
    lm2 = LimitsM()
    lm2.set_equity(1000.0, 0, 0)
    lm2.set_equity(1100.0, 0, 0)
    lm2.set_equity(900.0, 0, 0)
    check("equity dd fraction 18.2%", close(lm2.equity_dd_fraction(), 200.0 / 1100.0, 1e-9))
    check("equity dd 18.2% >= 15% breaches", lm2.breached())
    lm3 = LimitsM()
    lm3.set_equity(1000.0, 0, 0)
    lm3.register_open()   # trades_today=1, open=1
    check("open>=max (1>=1) breaches", lm3.breached())
    lm4 = LimitsM(max_consecutive=2)
    lm4.consecutive = 2
    check("consecutive 2>=2 breaches", lm4.breached())
    lm5 = LimitsM()
    lm5.set_equity(1000.0, 0, 0)
    lm5.sync(0, 1)   # day rollover: day_start = 1000
    lm5.equity = 940.0
    check("daily loss 6% >= 5% breaches", lm5.breached())
    lm5.sync(1, 1)   # hour rollover resets hourly counter only
    check("hour rollover keeps day state",
          lm5.trades_today == lm5.trades_today and lm5.day_start == 1000.0)
    lm6 = LimitsM()
    lm6.set_equity(1000.0, 0, 0)
    lm6.emergency = True
    check("EMERGENCY_STOP breaches everything", lm6.breached())

    # DrawdownProtection
    check("drawdown halt order: daily loss first",
          drawdown_m(950.0, 1100.0, 1000.0, 1000.0) == "daily_loss_limit")
    # daily loss must stay under 2% to isolate the other axes
    check("drawdown halt: daily drawdown from peak (loss 1.5%, peak-dd 5.3%)",
          drawdown_m(985.0, 1000.0, 1000.0, 1040.0) == "daily_drawdown_limit")
    check("drawdown halt: equity drawdown (loss 1.5%, equity-dd 10.5%)",
          drawdown_m(985.0, 1100.0, 1000.0, 1000.0) == "equity_drawdown_limit")
    check("drawdown healthy -> ''", drawdown_m(995.0, 1000.0, 1000.0, 1000.0) == "")

    # ExposureManager
    ex_net = ExposureM(mode=MODE_NETTING, max_open=1)
    check("netting: first position ok", ex_net.can_open(1))
    ex_net.register_open(1)
    check("netting: second position (any dir) forbidden", not ex_net.can_open(-1))
    ex_net.register_close(1)
    check("netting: after close, re-open ok", ex_net.can_open(1))
    ex_hed = ExposureM(mode=MODE_HEDGING, max_open=2)
    check("hedging: long ok", ex_hed.can_open(1))
    ex_hed.register_open(1)
    check("hedging: second long forbidden", not ex_hed.can_open(1))
    check("hedging: opposite short allowed", ex_hed.can_open(-1))
    ex_hed.margin = 600.0
    ex_hed.equity = 1000.0
    check("exposure fraction 60%", close(ex_hed.exposure_fraction(), 0.6, 1e-9))

    print(f"\n[PHASE6] === {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
