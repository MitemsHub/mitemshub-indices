"""v26.26 money layer, ported from MitemshubAI.mq5 for offline certification.

Mirrors the exact entry-chain money math so replays test the system that
actually trades:
  - CalibTickValue(): geometry overrules broker tick value when they deviate >5%
    (v26.25; V75 broker feeds 0.0001, geometry says 0.01)
  - CalculateVolume(): risk_money / risk_per_lot  (OpenTrade, line ~2905)
  - NormalizeVolume(): floor to lot step, clamp to [min_lot, max_lot] (line 3178)
  - GetScaledVolume(): vol *= 0.75^consec_loss, floor 0.30 (v23; preset values)
  - EFFECTIVE-RISK GUARDRAIL: skip if min-lot risk > 20% of equity (line 2915)
  - InpMicroFitPct: NOT present on the main path (CB path only) — at $50 the
    desired 0.0035 lots clamps to min lot 0.01 = 1.29R of true risk, inside cap
  - equity compounds with each closed trade (g_eq = account equity in the EA)

V75 money truth (calibrated): tick_size 0.01, tick_value 0.01 per 0.01 lot
=> $1.00 per index-unit per 1.0 lot (verified against the 2026-09-03 ledger:
   +$7.55 / 251.55 pts / 0.03 lots).
"""
from __future__ import annotations

# ---- preset constants (MitemshubAI_VOL75_FINAL.set + source defaults) -------
RISK_PER_TRADE = 0.005          # InpRiskPerTrade (0.5%)
MAX_EFF_RISK_PCT = 20.0         # InpMaxEffectiveRiskPct
SCALE_AFTER_LOSS = True         # InpScaleAfterLoss
SCALE_FACTOR = 0.75             # InpScaleFactor
MIN_VOL_SCALE = 0.30            # InpMinVolScale
MIN_LOT = 0.01                  # V75 broker spec
MAX_LOT = 100.0
LOT_STEP = 0.01
# calibrated: $ per price-unit per 1.0 lot
DOLLAR_PER_UNIT_PER_LOT = 1.009  # measured 2026-09-03 (slight USD/ZAR fr)


def calibrated_tick_value(tick_size: float, contract_size: float = 1.0,
                          broker_value: float | None = None) -> float:
    """v26.25 CalibTickValue(): geometry wins when the broker number deviates."""
    geo = tick_size * contract_size * DOLLAR_PER_UNIT_PER_LOT
    if broker_value is not None and broker_value > 0:
        dev = abs(broker_value - geo) / geo
        if dev > 0.05:
            return geo          # override + loud log in the EA
        return broker_value
    return geo


def normalize_volume(vol: float) -> float:
    """OpenTrade's NormalizeVolume() (line 3178): floor to step, clamp."""
    vol = (int(vol / LOT_STEP)) * LOT_STEP
    if vol < MIN_LOT:
        vol = MIN_LOT
    if vol > MAX_LOT:
        vol = MAX_LOT
    return round(vol, 2)


def scaled_volume(base_vol: float, consec_loss: int) -> float:
    """GetScaledVolume() (line 2825)."""
    if not SCALE_AFTER_LOSS or consec_loss <= 0:
        return base_vol
    scale = max(SCALE_FACTOR ** consec_loss, MIN_VOL_SCALE)
    return base_vol * scale


class MoneySim:
    """Simulates the EA entry chain bar-by-bar with compounding equity."""

    def __init__(self, equity: float):
        self.eq = equity
        self.consec = 0
        self.events: list[dict] = []

    def evaluate_entry(self, stop_dist: float) -> dict:
        """Exact OpenTrade() money chain. Returns dict with decision + values.

        stop_dist: structural stop in index units (from the signal engine).
        """
        risk_money = self.eq * RISK_PER_TRADE                     # ml_mult = 1.0 cold
        risk_per_lot = stop_dist * DOLLAR_PER_UNIT_PER_LOT        # (sd/tick)*tv
        if risk_per_lot <= 0:
            return {"trade": False, "reason": "bad-stop"}
        vol = risk_money / risk_per_lot
        vol = normalize_volume(vol)
        vol = normalize_volume(scaled_volume(vol, self.consec))
        eff_risk = vol * risk_per_lot
        cap = self.eq * MAX_EFF_RISK_PCT / 100.0
        if eff_risk > cap:
            return {"trade": False, "reason": "min-lot-risk",
                    "eff": eff_risk, "cap": cap}
        return {"trade": True, "vol": vol, "eff_risk": eff_risk,
                "r_dollar": eff_risk, "eq": self.eq}


def run_money_replay(trades: list[dict], equity0: float,
                     consec0: int = 0) -> dict:
    """Replay a signal-engine trade list through the money layer.

    Each trade dict needs: sd (stop dist in index units), r (result in R,
    measured on the stop). Equity compounds on the EA's true effective risk.
    """
    sim = MoneySim(equity0)
    sim.consec = consec0
    out = []
    eq = equity0
    for t in trades:
        d = sim.evaluate_entry(t["sd"])
        row = {**t, **{k: v for k, v in d.items() if k != "trade"},
               "taken": d["trade"], "eq_before": round(eq, 2)}
        if d["trade"]:
            money = d["eff_risk"] * t["r"]
            eq += money
            sim.eq = eq
            # loss-streak on R outcome (matches PostTradeReview)
            sim.consec = sim.consec + 1 if t["r"] <= 0 else 0
            row["pnl"] = round(money, 2)
            row["eq_after"] = round(eq, 2)
            row["risk_pct"] = round(d["eff_risk"] / eq * 100, 1)
        else:
            row["pnl"] = 0.0
            row["eq_after"] = round(eq, 2)
        out.append(row)
    taken = [t for t in out if t["taken"]]
    skipped = [t for t in out if not t["taken"]]
    return {
        "equity0": equity0,
        "equity_final": round(eq, 2),
        "trades_offered": len(out),
        "taken": len(taken),
        "skipped": len(skipped),
        "total_pnl": round(eq - equity0, 2),
        "max_risk_pct": max((t.get("risk_pct", 0) for t in taken), default=0),
        "worst_streak_seen": max((t.get("risk_pct", 0) for t in taken
                                  if t["r"] <= 0), default=0),
        "detail": out,
    }


if __name__ == "__main__":
    import json, sys
    rep = json.load(open("artifacts/v75_replay/replay_report.json"))
    for eq0 in (50.0, 25.0):
        res = run_money_replay(rep["trades"], eq0)
        print(f"=== equity ${eq0:.0f} ===")
        print(json.dumps({k: v for k, v in res.items() if k != "detail"}, indent=1))
        for t in res["detail"]:
            mark = "TAKE " if t["taken"] else "SKIP "
            extra = (f"risk={t['risk_pct']}% vol={t.get('vol')}"
                     if t["taken"] else f"({t.get('reason')})")
            print(f"{mark} {t['t']} {t['dir']:<4} sd={t['sd']:>6.0f} "
                  f"R={t['r']:+.2f} pnl={t['pnl']:+7.2f} eq={t['eq_after']:>7.2f} {extra}")
