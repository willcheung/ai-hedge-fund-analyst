from __future__ import annotations

from datetime import datetime, timezone

from trading_execution.broker.ibkr_adapter import IBKRSettings
from trading_execution.stream_store import StreamStore
from trading_execution.streamer import MESStreamer, StreamStatus


class FakeTicker:
    bid = 7443.25
    ask = 7443.5
    last = 7443.5
    bidSize = 8
    askSize = 33
    lastSize = 1
    marketDataType = 1


class FakeContract:
    localSymbol = "MESM6"
    symbol = "MES"
    conId = 770561194


def test_streamer_writes_quote_and_flushes_bar(tmp_path):
    store = StreamStore(tmp_path / "stream.sqlite3")
    streamer = MESStreamer(settings=IBKRSettings(port=4001), store=store)
    ts = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)

    streamer.record_tick(FakeTicker(), FakeContract(), received_at=ts)
    streamer.record_tick(FakeTicker(), FakeContract(), received_at=ts.replace(second=1))

    quote = store.latest_quote("MES")
    bars = store.latest_bars_1s("MES", limit=10)

    assert quote is not None
    assert quote.contract == "MESM6"
    assert quote.bid == 7443.25
    assert quote.ask == 7443.5
    assert quote.spread == 0.25
    assert len(bars) == 1
    assert bars[0].close == 7443.5


def test_stream_status_reports_quote_age(tmp_path):
    store = StreamStore(tmp_path / "stream.sqlite3")
    streamer = MESStreamer(settings=IBKRSettings(port=4001), store=store)
    ts = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)
    streamer.record_tick(FakeTicker(), FakeContract(), received_at=ts)

    status = StreamStatus.from_store(store, now=ts.replace(second=3), stale_after_seconds=10)

    assert status.as_dict()["ok"] is True
    assert status.as_dict()["latest_quote_age_seconds"] == 3.0
    assert status.as_dict()["latest_quote"]["contract"] == "MESM6"
