from __future__ import annotations

from dataclasses import dataclass, field

from synthetic_trader.config import RiskConfig
from synthetic_trader.domain import OrderIntent, TradeOutcome, TradeSignal
from synthetic_trader.features.indicators import clamp


@dataclass
class RiskState:
    equity: float
    day_start_equity: float
    open_positions: int = 0
    consecutive_losses: int = 0
    realized_pnl: float = 0.0
    trades_today: int = 0
    session_day: int | None = None


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    intent: OrderIntent | None
    reasons: tuple[str, ...]


class RiskEngine:
    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self.state = RiskState(
            equity=config.starting_equity,
            day_start_equity=config.starting_equity,
        )

    def evaluate(self, signal: TradeSignal) -> RiskDecision:
        reasons: list[str] = []
        min_confidence = signal.min_confidence
        if self.state.open_positions >= self.config.max_open_positions:
            reasons.append("max open positions reached")
        if self.state.consecutive_losses >= self.config.max_consecutive_losses:
            reasons.append("consecutive-loss circuit breaker active")
        if self.daily_drawdown_fraction() >= self.config.max_daily_loss_fraction:
            reasons.append("daily loss limit reached")
        if signal.confidence < min_confidence:
            reasons.append("signal confidence below risk threshold")
        if signal.reward_risk < self.config.min_reward_risk:
            reasons.append("reward/risk below minimum")
        if signal.snapshot.features.get("range_z_50", 0.0) > self.config.max_volatility_z:
            reasons.append("current candle volatility is statistically extreme")

        if reasons:
            return RiskDecision(False, None, tuple(reasons))

        risk_budget = self.state.equity * self.config.risk_per_trade
        quality = clamp(
            (signal.confidence - min_confidence) / max(1.0 - min_confidence, 1e-9),
            0.0,
            1.0,
        )
        stake = max(self.config.stake_floor, risk_budget * (0.55 + 0.70 * quality))
        stake = min(stake, risk_budget * 1.25)
        intent = OrderIntent(
            signal=signal,
            stake=round(stake, 2),
            max_loss=round(stake, 2),
            metadata={
                "equity": round(self.state.equity, 2),
                "risk_budget": round(risk_budget, 2),
                "quality": round(quality, 4),
            },
        )
        return RiskDecision(True, intent, ("risk approved",))

    def register_open(self) -> None:
        self.state.open_positions += 1
        self.state.trades_today += 1

    def register_outcome(self, outcome: TradeOutcome) -> None:
        if self.state.open_positions > 0:
            self.state.open_positions -= 1
        self.state.realized_pnl += outcome.pnl
        self.state.equity += outcome.pnl
        if outcome.pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0

    def reset_daily_limits(self) -> None:
        self.state.day_start_equity = self.state.equity
        self.state.consecutive_losses = 0
        self.state.trades_today = 0

    def sync_session_day(self, session_day: int) -> bool:
        if self.state.session_day is None:
            self.state.session_day = session_day
            return False
        if session_day == self.state.session_day:
            return False
        self.state.session_day = session_day
        self.reset_daily_limits()
        return True

    def daily_drawdown_fraction(self) -> float:
        loss = max(0.0, self.state.day_start_equity - self.state.equity)
        return loss / max(self.state.day_start_equity, 1e-9)
