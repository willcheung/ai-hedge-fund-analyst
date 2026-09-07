from __future__ import annotations

from trading_execution.strategy import StrategySignal
from trading_execution.strategies.opening_range_vwap import opening_range_vwap_signal


def base_levels(**overrides):
    data = {
        "symbol": "MES",
        "latest_quote": {
            "symbol": "MES",
            "contract": "MESM6",
            "bid": 100.0,
            "ask": 100.25,
            "last": 100.25,
            "spread": 0.25,
            "market_data_type": 1,
            "received_at_utc": "2026-06-09T14:00:00+00:00",
        },
        "vwap": 100.0,
        "or15_high": 101.0,
        "or15_low": 99.0,
        "overnight_high": 103.0,
        "overnight_low": 97.0,
    }
    data.update(overrides)
    return data


def test_signal_no_trade_when_stream_stale():
    signal = opening_range_vwap_signal(base_levels(), stream_ok=False)

    assert signal.state == "NO_TRADE"
    assert signal.reason == "stream_stale_or_missing"


def test_signal_setup_forming_before_or15_and_vwap_are_available():
    signal = opening_range_vwap_signal(base_levels(vwap=None, or15_high=None, or15_low=None))

    assert signal.state == "SETUP_FORMING"
    assert signal.reason == "waiting_for_or15_and_vwap"


def test_long_entry_ready_above_or15_and_vwap_with_structured_stop_target():
    levels = base_levels(
        latest_quote={
            "symbol": "MES",
            "contract": "MESM6",
            "bid": 101.25,
            "ask": 101.5,
            "last": 101.5,
            "spread": 0.25,
            "market_data_type": 1,
            "received_at_utc": "2026-06-09T14:00:00+00:00",
        },
        vwap=100.5,
        or15_high=101.0,
        or15_low=99.0,
    )

    signal = opening_range_vwap_signal(levels)

    assert signal.state == "ENTRY_READY"
    assert signal.side == "BUY"
    assert signal.entry_price == 101.5
    assert signal.stop_price == 100.5
    assert signal.target_price == 103.0
    assert signal.risk_points == 1.0
    assert signal.reward_points == 1.5


def test_short_entry_ready_below_or15_and_vwap_with_structured_stop_target():
    levels = base_levels(
        latest_quote={
            "symbol": "MES",
            "contract": "MESM6",
            "bid": 98.5,
            "ask": 98.75,
            "last": 98.5,
            "spread": 0.25,
            "market_data_type": 1,
            "received_at_utc": "2026-06-09T14:00:00+00:00",
        },
        vwap=99.5,
        or15_high=101.0,
        or15_low=99.0,
    )

    signal = opening_range_vwap_signal(levels)

    assert signal.state == "ENTRY_READY"
    assert signal.side == "SELL"
    assert signal.entry_price == 98.5
    assert signal.stop_price == 99.5
    assert signal.target_price == 97.0
    assert signal.risk_points == 1.0
    assert signal.reward_points == 1.5


def test_wait_when_inside_range():
    signal = opening_range_vwap_signal(base_levels())

    assert signal.state == "WAIT"
    assert signal.reason == "inside_or15_or_not_aligned_with_vwap"


def test_blocks_entry_when_bid_ask_are_ibkr_invalid_sentinels():
    levels = base_levels(
        latest_quote={
            "symbol": "MES",
            "contract": "MESM6",
            "bid": -1.0,
            "ask": -1.0,
            "last": 102.0,
            "spread": 0.0,
            "market_data_type": 1,
            "received_at_utc": "2026-06-09T14:00:00+00:00",
        },
        vwap=100.0,
        or15_high=101.0,
        or15_low=99.0,
    )

    signal = opening_range_vwap_signal(levels)

    assert signal.state == "NO_TRADE"
    assert signal.reason == "invalid_bid_ask"


def test_exit_now_for_long_stop_or_target():
    stop_signal = opening_range_vwap_signal(base_levels(latest_quote={**base_levels()["latest_quote"], "last": 99.5}), position_side="BUY", stop_price=100.0, target_price=103.0)
    target_signal = opening_range_vwap_signal(base_levels(latest_quote={**base_levels()["latest_quote"], "last": 103.25}), position_side="BUY", stop_price=100.0, target_price=103.0)

    assert stop_signal.state == "EXIT_NOW"
    assert stop_signal.exit_reason == "stop_hit"
    assert target_signal.state == "EXIT_NOW"
    assert target_signal.exit_reason == "target_hit"


def test_exit_now_for_short_stop_or_target():
    stop_signal = opening_range_vwap_signal(base_levels(latest_quote={**base_levels()["latest_quote"], "last": 100.5}), position_side="SELL", stop_price=100.0, target_price=97.0)
    target_signal = opening_range_vwap_signal(base_levels(latest_quote={**base_levels()["latest_quote"], "last": 96.75}), position_side="SELL", stop_price=100.0, target_price=97.0)

    assert stop_signal.state == "EXIT_NOW"
    assert stop_signal.exit_reason == "stop_hit"
    assert target_signal.state == "EXIT_NOW"
    assert target_signal.exit_reason == "target_hit"
