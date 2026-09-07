from __future__ import annotations

from datetime import datetime, timezone

from trading_execution.backtest.engine import BacktestParams, backtest_or_vwap
from trading_execution.stream_state import Bar1s


def bar(ts: str, price: float, *, high: float | None = None, low: float | None = None, volume: float = 1.0) -> Bar1s:
    return Bar1s(
        symbol="MES",
        ts_utc=datetime.fromisoformat(ts).replace(tzinfo=timezone.utc),
        open=price,
        high=price if high is None else high,
        low=price if low is None else low,
        close=price,
        volume_proxy=volume,
        bid=price - 0.25,
        ask=price,
        spread=0.25,
    )


def test_backtest_takes_long_breakout_and_target_with_pessimistic_entry_fill():
    # 13:30 UTC == 09:30 ET. OR15 high is 101 and VWAP is below breakout.
    bars = [
        bar("2026-06-09T13:30:00+00:00", 100, high=100, low=99),
        bar("2026-06-09T13:44:59+00:00", 100, high=101, low=99),
        bar("2026-06-09T13:45:01+00:00", 101.5, high=101.5, low=101.5),
        bar("2026-06-09T13:46:00+00:00", 103.5, high=103.5, low=103.5),
    ]

    report = backtest_or_vwap(bars, BacktestParams(slippage_ticks=1, tick_size=0.25, dollars_per_point=5, contracts=2))

    assert report.metrics.total_trades == 1
    trade = report.trades[0]
    assert trade.side == "BUY"
    assert trade.entry_fill == 101.75  # signal entry 101.5 + 1 tick
    assert trade.exit_reason == "target_hit"
    assert report.metrics.wins == 1
    assert report.verdict in {"REFINE", "PAPER_FORWARD_TEST"}


def test_backtest_uses_pessimistic_stop_first_when_stop_and_target_same_bar():
    bars = [
        bar("2026-06-09T13:30:00+00:00", 100, high=100, low=99),
        bar("2026-06-09T13:44:59+00:00", 100, high=101, low=99),
        bar("2026-06-09T13:45:01+00:00", 101.5, high=101.5, low=101.5),
        # Long signal stop from strategy is VWAP-ish near 100; target near 103.
        bar("2026-06-09T13:46:00+00:00", 101, high=104, low=99),
    ]

    report = backtest_or_vwap(bars, BacktestParams(slippage_ticks=1, tick_size=0.25, dollars_per_point=5, contracts=1))

    assert report.metrics.total_trades == 1
    assert report.trades[0].exit_reason == "stop_hit"
    assert report.trades[0].r_multiple < 0


def test_backtest_blocks_wide_spreads():
    bars = [
        bar("2026-06-09T13:30:00+00:00", 100, high=100, low=99),
        bar("2026-06-09T13:44:59+00:00", 100, high=101, low=99),
        Bar1s(symbol="MES", ts_utc=datetime.fromisoformat("2026-06-09T13:45:01+00:00"), open=101.5, high=101.5, low=101.5, close=101.5, volume_proxy=1, bid=101.0, ask=101.75, spread=0.75),
    ]

    report = backtest_or_vwap(bars, BacktestParams(max_spread=0.25))

    assert report.metrics.total_trades == 0
    assert report.no_trade_reasons.get("spread_too_wide") == 1
