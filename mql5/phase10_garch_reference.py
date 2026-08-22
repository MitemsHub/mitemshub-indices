#!/usr/bin/env python3
"""Generate the LOCKED EGARCH reference numbers for Tests/Phase10Tests.mq5.

The Phase-10 step-1 contract: the MQL5 CGarchForecaster (extracted verbatim
from BandBackTests) must reproduce, within floating-point tolerance:

  mode 0 (online-SGD)  == the REAL Python EGARCHVarianceForecaster
                         (src/synthetic_trader/models/garch.py)
  mode 1 (calibrated)  == this fixed-params replication of the same recursion

This script:
  1. builds a fixed 80-return sequence (the exact literals embedded in the
     .mq5 test — no sin/cos divergence risk, both sides consume identical
     inputs),
  2. runs the real Python forecaster over it (mode-0 reference),
  3. runs a faithful fixed-params replication over it (mode-1 reference),
     and SELF-VALIDATES the replication against the Python forecaster by
     zeroing the SGD step, so a regression in the reference generator
     itself fails loudly here rather than in the tester,
  4. prints the three MQL5 literal arrays to paste into Phase10Tests.mq5.

Run:  python mql5/phase10_garch_reference.py
"""
import math
import sys

sys.path.insert(0, "src")

from synthetic_trader.models.garch import EGARCHVarianceForecaster

N = 80
RETURNS = [0.001 * math.sin(0.7 * i) + 0.0005 * math.cos(1.3 * i) for i in range(N)]
# Exercise the obs-50 log-var reinit and the clamp path with real shocks.
RETURNS[23] = 0.02
RETURNS[41] = -0.015
RETURNS[67] = 0.03

EZ = 0.7979
OMEGA, ALPHA, GAMMA, BETA = -1.115, 0.077, 0.011, 0.918  # calibrated R_75
BUF = 50
WARMUP = 30


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def fixed_mode_reference(returns, apply_sgd=False):
    """Faithful port of the MQL5 EgarchUpdate recursion.

    apply_sgd=False reproduces mode 1 (calibrated fixed — the production
    estimator) starting from the calibrated params.  apply_sgd=True
    reproduces mode 0 starting from the PYTHON SGD defaults (GARCHState),
    and must equal the real Python forecaster (self-validated below).
    """
    if apply_sgd:
        omega, alpha, gamma, beta = -2.0, 0.10, -0.05, 0.85   # GARCHState defaults
    else:
        omega, alpha, gamma, beta = OMEGA, ALPHA, GAMMA, BETA  # calibrated R_75
    log_var = math.log(0.0004)
    obs = 0
    buf = []
    gsq = {"omega": 1e-6, "alpha": 1e-6, "gamma": 1e-6, "beta": 1e-6}
    out = []
    for r in returns:
        obs += 1
        if obs <= BUF:
            buf.append(r)
            if obs < WARMUP:
                out.append(math.exp(log_var / 2.0))
                continue
            if obs == BUF:
                msq = sum(x * x for x in buf) / len(buf)
                log_var = math.log(max(msq, 1e-10))
        sigma_t = math.exp(_clamp(log_var, -30.0, 5.0) / 2.0)
        z_t = r / max(sigma_t, 1e-10)
        shock = abs(z_t) - EZ
        log_var_new = omega + alpha * shock + gamma * z_t + beta * log_var
        if apply_sgd:
            persistence = beta + alpha * (1.0 - gamma * gamma / 2.0)
            new_beta = beta
            if persistence > 0.999:
                new_beta = beta * 0.999 / persistence
            realized = 2.0 * math.log(max(abs(r), 1e-12))
            pred_err = realized - log_var
            g_om = pred_err
            g_al = pred_err * shock
            g_ga = pred_err * z_t
            g_be = pred_err * log_var
            gsq["omega"] = 0.99 * gsq["omega"] + 0.01 * g_om * g_om
            gsq["alpha"] = 0.99 * gsq["alpha"] + 0.01 * g_al * g_al
            gsq["gamma"] = 0.99 * gsq["gamma"] + 0.01 * g_ga * g_ga
            gsq["beta"] = 0.99 * gsq["beta"] + 0.01 * g_be * g_be
            lr = 0.01
            omega += (lr / (math.sqrt(gsq["omega"]) + 1e-8)) * g_om
            alpha = _clamp(alpha + (lr / (math.sqrt(gsq["alpha"]) + 1e-8)) * g_al, 0.0, 0.5)
            gamma = _clamp(gamma + (lr / (math.sqrt(gsq["gamma"]) + 1e-8)) * g_ga, -0.5, 0.5)
            beta = max(0.0, min(new_beta, 0.999))
        log_var = _clamp(log_var_new, -30.0, 5.0)
        out.append(math.exp(log_var / 2.0))
    return out


def main() -> None:
    # --- real Python forecaster (mode-0 reference) -----------------------
    fc = EGARCHVarianceForecaster(learning_rate=0.01)
    py_sigmas = []
    for r in RETURNS:
        feats = fc.update(r)
        py_sigmas.append(feats["garch_sigma"])

    # --- my mode-0 replication must equal the real forecaster ------------
    rep0 = fixed_mode_reference(RETURNS, apply_sgd=True)
    for i, (a, b) in enumerate(zip(py_sigmas, rep0)):
        rel = abs(a - b) / max(abs(b), 1e-30)
        if rel > 1e-12:
            print(f"REFERENCE SELF-CHECK FAILED at {i}: py={a!r} rep={b!r} rel={rel:.2e}")
            sys.exit(1)
    print("reference self-check: mode-0 replication == real Python forecaster (all 80 OK)")

    # --- fixed-params mode-1 reference -----------------------------------
    m1 = fixed_mode_reference(RETURNS, apply_sgd=False)

    def fmt(vals, name):
        lines = [f"   // {name} - {len(vals)} locked sigmas (from phase10_garch_reference.py)"]
        row = []
        for v in vals:
            row.append(repr(v))
            if len(row) == 4:
                lines.append("   " + ", ".join(row) + ",")
                row = []
        if row:
            lines.append("   " + ", ".join(row) + ",")
        return "\n".join(lines)

    ret_lines = [f"   // returns - {len(RETURNS)} literal inputs (identical to the generator)"]
    row = []
    for v in RETURNS:
        row.append(repr(v))
        if len(row) == 4:
            ret_lines.append("   " + ", ".join(row) + ",")
            row = []
    if row:
        ret_lines.append("   " + ", ".join(row) + ",")

    print("\n=== MQL5 LITERALS FOR Phase10Tests.mq5 ===\n")
    print("double G_REF_RETURNS[" + str(len(RETURNS)) + "] =\n  {")
    print("\n".join(ret_lines))
    print("  };")
    print()
    print("double G_REF_SIGMA_M1[" + str(len(m1)) + "] =\n  {")
    print(fmt(m1, "mode-1 calibrated-fixed"))
    print("  };")
    print()
    print("double G_REF_SIGMA_M0[" + str(len(py_sigmas)) + "] =\n  {")
    print(fmt(py_sigmas, "mode-0 online-SGD (real Python forecaster)"))
    print("  };")
    print()
    print(f"#checksum {sum(m1):.17g} {sum(py_sigmas):.17g}")


if __name__ == "__main__":
    main()
