"""Shared instrument-spec integrity guard and artifact stamp.

Any run that points certification tooling at a custom data directory must state
all broker geometry explicitly.  Default runs remain V75 because those defaults
are the registered V75 truth.
"""
from __future__ import annotations

import os

DEFAULT_DATA_DIR = os.path.join("artifacts", "v75_replay")
DEFAULT_SPREAD = 18.5
DEFAULT_USD_PER_UNIT_PER_LOT = 1.009
DEFAULT_MIN_LOT = 0.01
DEFAULT_LOT_STEP = 0.01
SPEC_KEYS = (
    "CERT_SPREAD",
    "CERT_USD_PER_UNIT_PER_LOT",
    "CERT_MIN_LOT",
    "CERT_LOT_STEP",
)
GUARD_VERSION = "assert_spec_integrity v1 (2026-09-05)"


def assert_spec_integrity() -> None:
    """Fail before data access when a custom data directory lacks broker specs."""
    if "CERT_DATA_DIR" not in os.environ:
        return
    missing = [key for key in SPEC_KEYS if key not in os.environ]
    if missing:
        raise SystemExit(
            "SPEC-INTEGRITY FAIL: CERT_DATA_DIR is set to "
            f"'{os.environ['CERT_DATA_DIR']}' but {', '.join(missing)} is/are not set "
            "explicitly. Cross-instrument cert runs must set ALL four spec "
            "variables (spread, usd_per_unit_per_lot, min_lot, lot_step) plus "
            "CERT_DATA_DIR — five in total. If this really is V75 data, set them "
            "to the V75 truth: CERT_SPREAD=18.5 "
            "CERT_USD_PER_UNIT_PER_LOT=1.009 CERT_MIN_LOT=0.01 "
            "CERT_LOT_STEP=0.01. An artifact whose sizing implies a lot grid the "
            "instrument cannot trade is invalid on its face."
        )


def spec_block(*, artifact: str | None = None, symbol: str = "Volatility 75 Index",
               data_dir: str | None = None, tp_mult: float | str | None = 2.4,
               stop_mult: float = 1.0, min_score_bonus: int = 0,
               cost_model: str | None = None) -> dict:
    """Return the effective broker/model spec for stamping into an artifact."""
    explicit = {key: key in os.environ for key in ("CERT_DATA_DIR",) + SPEC_KEYS}
    return {
        "schema": "mitemshub.artifact-spec.v1",
        "artifact": artifact,
        "symbol": symbol,
        "data_dir": data_dir or os.environ.get("CERT_DATA_DIR", DEFAULT_DATA_DIR),
        "spread": float(os.environ.get("CERT_SPREAD", str(DEFAULT_SPREAD))),
        "usd_per_unit_per_lot": float(os.environ.get(
            "CERT_USD_PER_UNIT_PER_LOT", str(DEFAULT_USD_PER_UNIT_PER_LOT))),
        "min_lot": float(os.environ.get("CERT_MIN_LOT", str(DEFAULT_MIN_LOT))),
        "lot_step": float(os.environ.get("CERT_LOT_STEP", str(DEFAULT_LOT_STEP))),
        "cost_model": cost_model or (
            "legacy cost-blind (CERT_COST_LEGACY=1)"
            if os.environ.get("CERT_COST_LEGACY", "0") == "1"
            else "spread-in-pnl (v26.36)"
        ),
        "geometry": {
            "tp_mult": tp_mult,
            "stop_mult": stop_mult,
            "min_score_bonus": min_score_bonus,
        },
        "explicit_env": explicit,
        "guard": GUARD_VERSION,
    }
