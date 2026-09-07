from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from trading_execution.historical_backfill import ibkr_bar_to_bar1s, store_historical_bars
from trading_execution.levels import calculate_mes_levels
from trading_execution.stream_store import StreamStore

ET = ZoneInfo("America/New_York")


@dataclass
class FakeIBKRBar:
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def et_dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=ET)


def test_ibkr_bar_to_bar1s_converts_datetime_to_utc_bar():
    raw = FakeIBKRBar(date=et_dt("2026-06-17T09:30:00"), open=100, high=102, low=99, close=101, volume=12)

    bar = ibkr_bar_to_bar1s(raw, symbol="MES")

    assert bar.symbol == "MES"
    assert bar.ts_utc == datetime(2026, 6, 17, 13, 30, tzinfo=timezone.utc)
    assert bar.open == 100
    assert bar.high == 102
    assert bar.low == 99
    assert bar.close == 101
    assert bar.volume_proxy == 12


def test_store_historical_bars_makes_late_login_levels_tradeable(tmp_path):
    store = StreamStore(tmp_path / "stream.sqlite3")
    raw_bars = [
        FakeIBKRBar(et_dt("2026-06-17T09:30:00"), 100, 101, 99, 100, 10),
        FakeIBKRBar(et_dt("2026-06-17T09:35:00"), 104, 105, 103, 104, 20),
        FakeIBKRBar(et_dt("2026-06-17T09:44:00"), 106, 107, 98, 106, 30),
        FakeIBKRBar(et_dt("2026-06-17T09:45:00"), 108, 109, 107, 108, 40),
    ]

    result = store_historical_bars(store, raw_bars, symbol="MES", contract="MESM6")
    bars = store.latest_bars_1s("MES", limit=10)
    quote = store.latest_quote("MES")
    levels = calculate_mes_levels(bars, latest_quote=quote, now=et_dt("2026-06-17T10:00:00")).as_dict()

    assert result["stored_bars"] == 4
    assert quote is not None
    assert quote.contract == "MESM6"
    assert levels["or15_high"] == 107
    assert levels["or15_low"] == 98
    assert levels["vwap"] is not None
