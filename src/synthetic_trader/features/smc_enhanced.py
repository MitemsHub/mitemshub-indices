"""Enhanced market structure detection using smartmoneyconcepts library.

Brings institutional-grade Smart Money Concepts (ICT/SMC) into the synthetic
indices engine.  Adapted for synthetic indices which use tick volume instead
of monetary volume — all volume inputs are replaced with tick counts.

Functions here are called alongside the existing market_structure.py features
to provide additional structural intelligence to the decision engine.
"""

from __future__ import annotations

import logging
import os
from statistics import mean

import pandas as pd

from synthetic_trader.domain import Candle

# Suppress the smartmoneyconcepts star-emoji print on import
os.environ.setdefault("SMC_CREDIT", "0")


def _candles_to_df(candles: list[Candle]) -> pd.DataFrame:
    """Convert internal Candle objects to a pandas DataFrame for smartmoneyconcepts."""
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    data = []
    for i, c in enumerate(candles):
        data.append({
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": 1,  # tick volume = 1 per candle (synthetic indices)
            "index": i,
        })
    return pd.DataFrame(data)


def _get_swing_highs_lows(candles: list[Candle]) -> pd.DataFrame | None:
    """Get swing highs/lows using smartmoneyconcepts."""
    try:
        from smartmoneyconcepts.smc import smc
        df = _candles_to_df(candles)
        if len(df) < 5:
            return None
        swings = smc.swing_highs_lows(df, swing_length=5)
        return swings
    except Exception:
        return None


def detect_smf_fvg(candles: list[Candle]) -> list[dict]:
    """Detect Fair Value Gaps using smartmoneyconcepts."""
    try:
        from smartmoneyconcepts.smc import smc
        df = _candles_to_df(candles)
        if len(df) < 3:
            return []
        fvgs = smc.fvg(df, join_consecutive=True)
        if fvgs is None or fvgs.empty:
            return []
        results = []
        for _, row in fvgs.iterrows():
            top = float(row.get("Top", 0)) if pd.notna(row.get("Top")) else 0.0
            bottom = float(row.get("Bottom", 0)) if pd.notna(row.get("Bottom")) else 0.0
            if top == 0 and bottom == 0:
                continue
            is_bullish = top > bottom
            results.append({
                "index": int(row.name) if hasattr(row, 'name') else 0,
                "top": top, "bottom": bottom,
                "direction": "bullish" if is_bullish else "bearish",
                "mitigated": pd.notna(row.get("MitigatedIndex")),
            })
        return results
    except Exception as e:
        logging.debug("[smc_enhanced] FVG detection failed: %s", e)
        return []


def detect_smc_bos_choch(candles: list[Candle]) -> dict:
    """Detect Break of Structure (BOS) and Change of Character (CHoCH)."""
    result = {"bos_up": 0, "bos_down": 0, "choch_up": 0, "choch_down": 0, "direction": "neutral"}
    try:
        from smartmoneyconcepts.smc import smc
        df = _candles_to_df(candles)
        swings = _get_swing_highs_lows(candles)
        if len(df) < 5 or swings is None or swings.empty:
            return result
        bos_choch_df = smc.bos_choch(df, swing_highs_lows=swings, close_break=True)
        if bos_choch_df is None or bos_choch_df.empty:
            return result
        last = bos_choch_df[bos_choch_df["BOS"].notna() | bos_choch_df["CHoCH"].notna()]
        if last.empty:
            return result
        row = last.iloc[-1]
        has_bos = pd.notna(row.get("BOS"))
        has_choch = pd.notna(row.get("CHoCH"))
        bullish = row.get("Bullish", row.get("bullish", False))
        bearish = row.get("Bearish", row.get("bearish", False))
        if has_bos and bullish:
            result["bos_up"] = 1
            result["direction"] = "bullish"
        elif has_bos and bearish:
            result["bos_down"] = 1
            result["direction"] = "bearish"
        elif has_choch and bullish:
            result["choch_up"] = 1
            result["direction"] = "bullish_reversal"
        elif has_choch and bearish:
            result["choch_down"] = 1
            result["direction"] = "bearish_reversal"
    except Exception as e:
        logging.debug("[smc_enhanced] BOS/CHoCH failed: %s", e)
    return result


def detect_smc_order_blocks(candles: list[Candle]) -> list[dict]:
    """Detect Order Blocks using smartmoneyconcepts."""
    try:
        from smartmoneyconcepts.smc import smc
        df = _candles_to_df(candles)
        swings = _get_swing_highs_lows(candles)
        if len(df) < 5 or swings is None or swings.empty:
            return []
        ob_df = smc.ob(df, swing_highs_lows=swings, close_mitigation=True)
        if ob_df is None or ob_df.empty:
            return []
        results = []
        for _, row in ob_df.iterrows():
            results.append({
                "index": int(row.name) if hasattr(row, 'name') else 0,
                "top": float(row.get("Top", 0)),
                "bottom": float(row.get("Bottom", 0)),
                "direction": "bullish" if row.get("Bullish", row.get("bullish", False)) else "bearish",
                "volume_score": 0.5,
            })
        return results
    except Exception as e:
        logging.debug("[smc_enhanced] Order Block detection failed: %s", e)
        return []


def detect_smc_liquidity(candles: list[Candle], range_percent: float = 0.01) -> dict:
    """Detect liquidity pools using smartmoneyconcepts."""
    result = {"highs_swept": 0, "lows_swept": 0, "cluster_high": 0.0, "cluster_low": 0.0}
    try:
        from smartmoneyconcepts.smc import smc
        df = _candles_to_df(candles)
        swings = _get_swing_highs_lows(candles)
        if len(df) < 5 or swings is None or swings.empty:
            return result
        liq_df = smc.liquidity(df, swing_highs_lows=swings, range_percent=range_percent)
        if liq_df is None or liq_df.empty:
            return result
        highs = liq_df[liq_df["Type"] == "high"] if "Type" in liq_df.columns else pd.DataFrame()
        lows = liq_df[liq_df["Type"] == "low"] if "Type" in liq_df.columns else pd.DataFrame()
        result["highs_swept"] = 1 if (not highs.empty and highs.iloc[-1].get("Swept", False)) else 0
        result["lows_swept"] = 1 if (not lows.empty and lows.iloc[-1].get("Swept", False)) else 0
        result["cluster_high"] = float(highs.iloc[-1].get("Price", 0)) if not highs.empty else 0.0
        result["cluster_low"] = float(lows.iloc[-1].get("Price", 0)) if not lows.empty else 0.0
    except Exception as e:
        logging.debug("[smc_enhanced] Liquidity detection failed: %s", e)
    return result


def smc_features(candles: list[Candle]) -> dict[str, float]:
    """Compute all SMC features and return as a flat dict for the decision engine.

    This function is called alongside market_structure_features() to provide
    additional institutional-grade structural intelligence.
    """
    if len(candles) < 5:
        return {
            "smc_fvg_count": 0.0,
            "smc_bullish_fvg": 0.0,
            "smc_bearish_fvg": 0.0,
            "smc_bos": 0.0,
            "smc_choch": 0.0,
            "smc_order_block_count": 0.0,
            "smc_ob_bullish": 0.0,
            "smc_ob_bearish": 0.0,
            "smc_ob_strength": 0.0,
            "smc_liq_sweep_high": 0.0,
            "smc_liq_sweep_low": 0.0,
        }

    fvgs = detect_smf_fvg(candles)
    bos_choch = detect_smc_bos_choch(candles)
    order_blocks = detect_smc_order_blocks(candles)
    liquidity = detect_smc_liquidity(candles)

    bullish_fvgs = [f for f in fvgs if f["direction"] == "bullish" and not f.get("mitigated", False)]
    bearish_fvgs = [f for f in fvgs if f["direction"] == "bearish" and not f.get("mitigated", False)]

    ob_bullish = [ob for ob in order_blocks if ob["direction"] == "bullish"]
    ob_bearish = [ob for ob in order_blocks if ob["direction"] == "bearish"]
    ob_strength = mean([ob["volume_score"] for ob in order_blocks]) if order_blocks else 0.5

    bos_score = 0.0
    if bos_choch["bos_up"]:
        bos_score = 1.0
    elif bos_choch["bos_down"]:
        bos_score = -1.0

    choch_score = 0.0
    if bos_choch["choch_up"]:
        choch_score = 1.0
    elif bos_choch["choch_down"]:
        choch_score = -1.0

    return {
        "smc_fvg_count": float(len(fvgs)),
        "smc_bullish_fvg": 1.0 if bullish_fvgs else 0.0,
        "smc_bearish_fvg": 1.0 if bearish_fvgs else 0.0,
        "smc_bos": bos_score,
        "smc_choch": choch_score,
        "smc_order_block_count": float(len(order_blocks)),
        "smc_ob_bullish": 1.0 if ob_bullish else 0.0,
        "smc_ob_bearish": 1.0 if ob_bearish else 0.0,
        "smc_ob_strength": ob_strength,
        "smc_liq_sweep_high": float(liquidity["highs_swept"]),
        "smc_liq_sweep_low": float(liquidity["lows_swept"]),
    }


