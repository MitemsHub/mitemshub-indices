from __future__ import annotations

from dataclasses import dataclass

from synthetic_trader.domain import Candle
from synthetic_trader.features.multi_timeframe_structure import build_structure_map


@dataclass(frozen=True)
class TopDownBias:
    direction: str
    reason: str
    invalidation_price: float | None
    confluence_score: float = 0.0
    bias_regime: str = "unknown"
    setup_regime: str = "unknown"
    confirmation_regime: str = "unknown"
    execution_regime: str = "unknown"
    structure_notes: tuple[str, ...] = ()


def infer_top_down_bias(
    *,
    symbol: str,
    bias_candles: list[Candle],
    setup_candles: list[Candle],
    confirmation_candles: list[Candle] | None = None,
    execution_candles: list[Candle] | None = None,
) -> TopDownBias:
    del symbol

    confirmation_role_candles = confirmation_candles or setup_candles
    execution_role_candles = execution_candles or confirmation_role_candles
    structure = build_structure_map(
        bias_candles=bias_candles,
        setup_candles=setup_candles,
        confirmation_candles=confirmation_role_candles,
        execution_candles=execution_role_candles,
    )
    return TopDownBias(
        direction=structure.bias_direction,
        reason="; ".join(structure.structure_notes),
        invalidation_price=structure.invalidation_price,
        confluence_score=structure.confluence_score,
        bias_regime=structure.bias_regime,
        setup_regime=structure.setup_regime,
        confirmation_regime=structure.confirmation_regime,
        execution_regime=structure.execution_regime,
        structure_notes=structure.structure_notes,
    )
