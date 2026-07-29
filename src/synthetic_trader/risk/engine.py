from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from synthetic_trader.config import RiskConfig
from synthetic_trader.domain import OrderIntent, TradeOutcome, TradeSignal
from synthetic_trader.features.indicators import clamp

if TYPE_CHECKING:
    from synthetic_trader.backtest.prop_firm import PropFirmBreachTracker, PropFirmProfile


@dataclass
class RiskState:
    equity: float
    day_start_equity: float
    open_positions: int = 0
    consecutive_losses: int = 0
    realized_pnl: float = 0.0
    trades_today: int = 0
    session_day: int | None = None
    initial_balance: float = 0.0  # For prop firm drawdown tracking


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    intent: OrderIntent | None
    reasons: tuple[str, ...]


class RiskEngine:
    def __init__(
        self,
        config: RiskConfig,
        prop_firm: PropFirmProfile | None = None,
        breach_tracker: PropFirmBreachTracker | None = None,
    ) -> None:
        self.config = config
        self.prop_firm = prop_firm
        self.breach_tracker = breach_tracker
        self.state = RiskState(
            equity=config.starting_equity,
            day_start_equity=config.starting_equity,
            initial_balance=config.starting_equity,
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

        # ── Prop firm constraints ──────────────────────────────
        # Track the first prop-firm breach reason so we only record once per evaluation
        prop_firm_breach_type: str | None = None
        prop_firm_breach_msg: str | None = None

        if self.prop_firm is not None:
            initial = self.state.initial_balance

            # 1) Daily loss limit (prop firm rule)
            prop_daily_loss = self.daily_drawdown_fraction()
            if prop_daily_loss >= self.prop_firm.max_daily_loss_pct:
                reasons.append(
                    f"prop firm daily loss limit ({self.prop_firm.max_daily_loss_pct:.0%}) reached"
                )
                if prop_firm_breach_type is None:
                    prop_firm_breach_type = "daily_loss"
                    prop_firm_breach_msg = f"Daily drawdown {prop_daily_loss:.1%} >= {self.prop_firm.max_daily_loss_pct:.0%}"

            # 2) Overall drawdown limit (prop firm rule — static, not trailing)
            overall_drawdown = max(0.0, initial - self.state.equity) / max(initial, 1e-9)
            if overall_drawdown >= self.prop_firm.max_overall_drawdown_pct:
                reasons.append(
                    f"prop firm max drawdown ({self.prop_firm.max_overall_drawdown_pct:.0%}) breached"
                )
                if prop_firm_breach_type is None:
                    prop_firm_breach_type = "max_drawdown"
                    prop_firm_breach_msg = f"Overall drawdown {overall_drawdown:.1%} >= {self.prop_firm.max_overall_drawdown_pct:.0%}"

            # 3) Risk per trade cap (prop firm rule)
            if self.prop_firm.risk_per_trade_pct > 0:
                max_risk_amount = initial * self.prop_firm.risk_per_trade_pct
                # The stake we're about to place must not exceed this
                # (stake check happens after reasons — we check intent below)

        if reasons:
            # Record exactly one breach per evaluation (the most severe)
            if self.breach_tracker is not None and prop_firm_breach_type is not None:
                self.breach_tracker.record_breach(
                    prop_firm_breach_type,
                    epoch=signal.snapshot.epoch,
                    message=prop_firm_breach_msg or prop_firm_breach_type,
                    equity=self.state.equity,
                )
            return RiskDecision(False, None, tuple(reasons))

        risk_budget = self.state.equity * self.config.risk_per_trade
        quality = clamp(
            (signal.confidence - min_confidence) / max(1.0 - min_confidence, 1e-9),
            0.0,
            1.0,
        )
        stake = max(self.config.stake_floor, risk_budget * (0.55 + 0.70 * quality))
        stake = min(stake, risk_budget * 1.25)

        # ── Enforce prop firm risk-per-trade cap ──────────────
        if self.prop_firm is not None and self.prop_firm.risk_per_trade_pct > 0:
            max_risk_amount = self.state.initial_balance * self.prop_firm.risk_per_trade_pct
            if stake > max_risk_amount:
                stake = max_risk_amount
                if self.breach_tracker is not None:
                    self.breach_tracker.record_breach(
                        "risk_per_trade",
                        epoch=signal.snapshot.epoch,
                        message=f"Stake capped to {max_risk_amount:.2f} (1.5% of initial)",
                        equity=self.state.equity,
                    )

        intent = OrderIntent(
            signal=signal,
            stake=round(stake, 2),
            max_loss=round(stake, 2),
            metadata={
                "equity": round(self.state.equity, 2),
                "risk_budget": round(risk_budget, 2),
                "quality": round(quality, 4),
                "prop_firm_active": self.prop_firm is not None,
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
