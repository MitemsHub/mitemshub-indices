"""Prop firm profile definitions for backtesting.

Defines the rules and constraints of funded trading accounts so that
the backtest runner can enforce real-world restrictions during
curve-fitting detection.  This ensures the strategy is tested under
the same conditions the trader will face on a live funded account.

Supported prop firms:
- Deriv Funded 2-Step (Forex)
- Deriv Funded Synthetic (Synthetic indices)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PropFirmProfile:
    """Complete prop firm rule set for backtesting.

    Parameters
    ----------
    name : str
        Human-readable name (e.g., "Deriv Funded 2-Step").
    max_daily_loss_pct : float
        Maximum daily loss as fraction of starting balance (e.g., 0.05 = 5%).
    max_overall_drawdown_pct : float
        Maximum overall drawdown as fraction of initial balance (e.g., 0.10 = 10%).
    profit_target_phase1_pct : float
        Profit target for Phase 1 as fraction (e.g., 0.10 = 10%).
    profit_target_phase2_pct : float
        Profit target for Phase 2 as fraction (e.g., 0.05 = 5%).
    leverage : int
        Leverage ratio (e.g., 30 means 1:30).
    risk_per_trade_pct : float
        Maximum risk per single trade idea as fraction of initial balance
        (e.g., 0.015 = 1.5%).  0 means no per-trade limit.
    min_trading_days_phase1 : int
        Minimum active trading days to pass Phase 1.
    min_trading_days_phase2 : int
        Minimum active trading days to pass Phase 2.
    min_daily_profit_pct : float
        Minimum realized profit on an active day (e.g., 0.005 = 0.5%).
    max_inactive_days : int
        Maximum consecutive inactive days before breach (e.g., 30).
    allow_hedging : bool
        Whether hedging within the same account is allowed.
    allow_synthetic_indices : bool
        Whether synthetic indices are permitted.
    """

    name: str = "Deriv Funded 2-Step"
    max_daily_loss_pct: float = 0.05
    max_overall_drawdown_pct: float = 0.10
    profit_target_phase1_pct: float = 0.10
    profit_target_phase2_pct: float = 0.05
    leverage: int = 30
    risk_per_trade_pct: float = 0.015
    min_trading_days_phase1: int = 3
    min_trading_days_phase2: int = 3
    min_daily_profit_pct: float = 0.005
    max_inactive_days: int = 30
    allow_hedging: bool = True
    allow_synthetic_indices: bool = True


# ── Pre-defined Profiles ────────────────────────────────────────────

DERIV_FUNDED_2STEP = PropFirmProfile(
    name="Deriv Funded 2-Step",
    max_daily_loss_pct=0.05,
    max_overall_drawdown_pct=0.10,
    profit_target_phase1_pct=0.10,
    profit_target_phase2_pct=0.05,
    leverage=30,
    risk_per_trade_pct=0.015,
    min_trading_days_phase1=3,
    min_trading_days_phase2=3,
    min_daily_profit_pct=0.005,
    max_inactive_days=30,
    allow_hedging=True,
    allow_synthetic_indices=True,
)

DERIV_SYNTHETIC = PropFirmProfile(
    name="Deriv Funded Synthetic",
    max_daily_loss_pct=0.04,  # 4% for synthetic plan
    max_overall_drawdown_pct=0.10,
    profit_target_phase1_pct=0.10,
    profit_target_phase2_pct=0.05,
    leverage=30,
    risk_per_trade_pct=0.015,
    min_trading_days_phase1=3,
    min_trading_days_phase2=3,
    min_daily_profit_pct=0.005,
    max_inactive_days=30,
    allow_hedging=True,
    allow_synthetic_indices=True,
)

# Registry for CLI lookup
PROP_FIRM_PROFILES: dict[str, PropFirmProfile] = {
    "deriv_2step": DERIV_FUNDED_2STEP,
    "deriv_synthetic": DERIV_SYNTHETIC,
}


def get_prop_firm_profile(name: str) -> PropFirmProfile | None:
    """Look up a prop firm profile by name (case-insensitive)."""
    return PROP_FIRM_PROFILES.get(name.lower().replace("-", "_").replace(" ", "_"))


@dataclass
class PropFirmBreachTracker:
    """Track prop firm rule violations during backtesting.

    Records every breach so the backtest report can show exactly
    how many times and which rules were violated.
    """

    initial_balance: float = 0.0
    daily_loss_breaches: int = 0
    drawdown_breaches: int = 0
    risk_per_trade_breaches: int = 0
    inactivity_breaches: int = 0
    total_breaches: int = 0
    breach_details: list[dict] = field(default_factory=list)

    def record_breach(
        self,
        rule: str,
        epoch: float,
        message: str,
        equity: float | None = None,
    ) -> None:
        """Record a prop firm rule violation."""
        self.total_breaches += 1
        detail = {
            "rule": rule,
            "epoch": epoch,
            "message": message,
            "breach_number": self.total_breaches,
        }
        if equity is not None:
            detail["equity"] = equity
        self.breach_details.append(detail)

        if rule == "daily_loss":
            self.daily_loss_breaches += 1
        elif rule == "max_drawdown":
            self.drawdown_breaches += 1
        elif rule == "risk_per_trade":
            self.risk_per_trade_breaches += 1
        elif rule == "inactivity":
            self.inactivity_breaches += 1

    @property
    def breached(self) -> bool:
        """Whether any breach occurred."""
        return self.total_breaches > 0

    def summary(self) -> dict:
        return {
            "total_breaches": self.total_breaches,
            "daily_loss_breaches": self.daily_loss_breaches,
            "drawdown_breaches": self.drawdown_breaches,
            "risk_per_trade_breaches": self.risk_per_trade_breaches,
            "inactivity_breaches": self.inactivity_breaches,
            "breach_details": self.breach_details[:10],  # First 10 for display
        }
