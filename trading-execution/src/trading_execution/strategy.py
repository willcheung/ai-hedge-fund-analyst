from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

SignalState = Literal["WAIT", "NO_TRADE", "SETUP_FORMING", "ENTRY_READY", "EXIT_NOW"]
SignalSide = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class StrategySignal:
    strategy: str
    symbol: str
    state: SignalState
    side: SignalSide | None
    reason: str
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    invalidation: str | None = None
    risk_points: float | None = None
    reward_points: float | None = None
    exit_reason: str | None = None
    levels: dict[str, Any] | None = None
    quote: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "symbol": self.symbol,
            "state": self.state,
            "side": self.side,
            "reason": self.reason,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "invalidation": self.invalidation,
            "risk_points": self.risk_points,
            "reward_points": self.reward_points,
            "exit_reason": self.exit_reason,
            "levels": self.levels,
            "quote": self.quote,
        }
