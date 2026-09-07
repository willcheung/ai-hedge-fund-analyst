from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from trading_execution.levels import calculate_mes_levels
from trading_execution.stream_state import Bar1s, QuoteState

ET = ZoneInfo("America/New_York")


def bar(ts_et: str, close: float, *, high: float | None = None, low: float | None = None, volume: float = 1.0) -> Bar1s:
    ts = datetime.fromisoformat(ts_et).replace(tzinfo=ET).astimezone(timezone.utc)
    return Bar1s(
        symbol="MES",
        ts_utc=ts,
        open=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume_proxy=volume,
        bid=close - 0.25,
        ask=close,
        spread=0.25,
    )


def test_calculate_mes_levels_computes_weighted_vwap_and_latest_quote():
    bars = [
        bar("2026-06-09T09:30:00", 100, volume=1),
        bar("2026-06-09T09:30:01", 102, volume=3),
    ]
    quote = QuoteState(
        symbol="MES",
        contract="MESM6",
        bid=101.75,
        ask=102.0,
        last=102.0,
        received_at_utc=bars[-1].ts_utc,
    )

    levels = calculate_mes_levels(bars, latest_quote=quote, now=bars[-1].ts_utc)

    data = levels.as_dict()
    assert data["symbol"] == "MES"
    assert data["latest_quote"]["contract"] == "MESM6"
    assert data["vwap"] == 101.5
    assert data["last_vs_vwap"] == 0.5


def test_calculate_mes_levels_uses_first_rth_minutes_for_opening_ranges():
    bars = [
        bar("2026-06-09T09:29:59", 90, high=200, low=80),  # not RTH / not OR
        bar("2026-06-09T09:30:00", 100, high=101, low=99),
        bar("2026-06-09T09:34:59", 105, high=106, low=104),
        bar("2026-06-09T09:35:00", 110, high=111, low=109),
        bar("2026-06-09T09:44:59", 115, high=116, low=114),
        bar("2026-06-09T09:45:00", 120, high=121, low=119),  # outside OR15
    ]

    levels = calculate_mes_levels(bars, latest_quote=None, now=bars[-1].ts_utc)
    data = levels.as_dict()

    assert data["or5_high"] == 106
    assert data["or5_low"] == 99
    assert data["or15_high"] == 116
    assert data["or15_low"] == 99
    assert data["or30_high"] == 121
    assert data["or30_low"] == 99


def test_calculate_mes_levels_computes_overnight_high_low_before_rth_open():
    bars = [
        bar("2026-06-09T08:00:00", 100, high=103, low=99),
        bar("2026-06-09T09:29:59", 101, high=104, low=98),
        bar("2026-06-09T09:30:00", 110, high=111, low=109),
    ]

    levels = calculate_mes_levels(bars, latest_quote=None, now=bars[-1].ts_utc)
    data = levels.as_dict()

    assert data["overnight_high"] == 104
    assert data["overnight_low"] == 98
    assert data["bars_used"] == 3
