#!/usr/bin/env python3
"""Bit-faithfulness gate: the fixed MQL5 EgarchUpdate port (mirrored here)
vs the real Python EGARCHVarianceForecaster.update() on real R_75 M5 closes."""
import csv
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
TF = 300
CORPUS_PATHS = [
    os.path.join(_HERE, "data", "backfill", "R_75_ticks.csv"),
    os.path.join(_HERE, "data", "R_75_ticks.csv"),
]


def load_m5_bars(paths):
    ticks = []
    seen = set()
    for p in paths:
        if not os.path.exists(p):
            continue
        with open(p, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            prev = None
            for row in reader:
                try:
                    epoch = float(row[0])
                    price = float(row[2])
                except (ValueError, IndexError):
                    continue
                if not (100.0 <= price <= 5000.0):
                    continue
                if prev is not None and abs(price - prev) / prev > 0.30:
                    continue
                k = round(epoch, 6)
                if k in seen:
                    continue
                seen.add(k)
                ticks.append((epoch, price))
                prev = price
    ticks.sort(key=lambda t: t[0])
    bars = []
    for epoch, price in ticks:
        bucket = int(epoch // TF)
        if bars and bars[-1][0] == bucket:
            b = bars[-1]
            bars[-1] = (bucket, b[1], max(b[2], price), min(b[3], price), price)
        else:
            bars.append((bucket, price, price, price, price))
    return bars


class _EAEgarch:
    """Exact mirror of the fixed MQL5 EgarchUpdate in BandBackTests.mq5."""

    def __init__(self):
        self.omega = -2.0
        self.alpha = 0.10
        self.gamma = -0.05
        self.beta = 0.85
        self.log_var = math.log(0.0004)
        self.obs = 0
        self.gsq = {"omega": 1e-6, "alpha": 1e-6, "gamma": 1e-6, "beta": 1e-6}
        self.ez = 0.7979
        self.buf = []
        self.last_sigma = 0.0

    def update(self, log_return):
        self.obs += 1
        if self.obs <= 50:
            self.buf.append(log_return)
            if self.obs < 30:
                # Python _default_features(): garch_sigma = sqrt(long_run_var)
                self.last_sigma = math.exp(self.log_var / 2.0)
                return
            if self.obs == 50:
                msq = sum(r * r for r in self.buf) / 50.0
                self.log_var = math.log(max(msq, 1e-10))
        sigma_t = math.exp(max(-30.0, min(5.0, self.log_var)) / 2.0)
        z_t = log_return / max(sigma_t, 1e-10)
        shock = abs(z_t) - self.ez
        log_var_new = self.omega + self.alpha * shock + self.gamma * z_t + self.beta * self.log_var
        persistence = self.beta + self.alpha * (1.0 - self.gamma * self.gamma / 2.0)
        new_beta = self.beta
        if persistence > 0.999:
            new_beta = self.beta * 0.999 / persistence
        realized = 2.0 * math.log(max(abs(log_return), 1e-12))
        pred_err = realized - self.log_var
        g_om, g_al, g_ga, g_be = pred_err, pred_err * shock, pred_err * z_t, pred_err * self.log_var
        for name, g in (("omega", g_om), ("alpha", g_al), ("gamma", g_ga), ("beta", g_be)):
            self.gsq[name] = 0.99 * self.gsq[name] + 0.01 * g * g
        lr = 0.01
        self.omega += (lr / (math.sqrt(self.gsq["omega"]) + 1e-8)) * g_om
        self.alpha = max(0.0, min(0.5, self.alpha + (lr / (math.sqrt(self.gsq["alpha"]) + 1e-8)) * g_al))
        self.gamma = max(-0.5, min(0.5, self.gamma + (lr / (math.sqrt(self.gsq["gamma"]) + 1e-8)) * g_ga))
        self.beta = max(0.0, min(new_beta, 0.999))
        self.log_var = max(-30.0, min(5.0, log_var_new))
        self.last_sigma = math.exp(self.log_var / 2.0)


def main():
    from synthetic_trader.models.garch import EGARCHVarianceForecaster

    bars = load_m5_bars(CORPUS_PATHS)
    closes = [b[4] for b in bars]
    print(f"bars={len(closes)}  close {closes[0]:.2f}..{closes[-1]:.2f}")

    py = EGARCHVarianceForecaster()
    ea = _EAEgarch()
    first_div = None
    max_diff = 0.0
    ndiv = 0
    for i in range(1, len(closes)):
        lr_ = math.log(closes[i] / closes[i - 1]) if closes[i - 1] > 0 else 0.0
        pf = py.update(lr_)
        ea.update(lr_)
        s_py = pf["garch_sigma"] if isinstance(pf, dict) else py.state.conditional_volatility
        d = abs(s_py - ea.last_sigma)
        if d > max_diff:
            max_diff = d
        if d > 1e-12 and first_div is None:
            first_div = (i, d, s_py, ea.last_sigma)
        if d > 1e-9:
            ndiv += 1
    print(f"first divergence bar={first_div}")
    print(f"max abs diff={max_diff:.3e}  bars diverging >1e-9: {ndiv} of {len(closes)-1}")
    if first_div is None:
        print("BIT-FAITHFUL: EA mirror == Python forecaster to 1e-12")
        return 0
    print("DIVERGENCE REMAINS")
    return 1


if __name__ == "__main__":
    sys.exit(main())
