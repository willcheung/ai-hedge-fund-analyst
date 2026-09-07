from __future__ import annotations

from trading_execution.strategy import StrategySignal


def test_strategy_signal_serializes_entry_and_exit_fields():
    signal = StrategySignal(
        strategy="or-vwap",
        symbol="MES",
        state="ENTRY_READY",
        side="BUY",
        reason="breakout_above_or15_and_vwap",
        entry_price=101.25,
        stop_price=99.75,
        target_price=103.5,
        invalidation="last_price_back_below_vwap",
        risk_points=1.5,
        reward_points=2.25,
    )

    assert signal.as_dict() == {
        "strategy": "or-vwap",
        "symbol": "MES",
        "state": "ENTRY_READY",
        "side": "BUY",
        "reason": "breakout_above_or15_and_vwap",
        "entry_price": 101.25,
        "stop_price": 99.75,
        "target_price": 103.5,
        "invalidation": "last_price_back_below_vwap",
        "risk_points": 1.5,
        "reward_points": 2.25,
        "exit_reason": None,
        "levels": None,
        "quote": None,
    }
