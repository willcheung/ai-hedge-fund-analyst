from __future__ import annotations

from datetime import datetime, timezone

from trading_execution.stream_state import Bar1s, QuoteState
from trading_execution.stream_store import StreamStore


def test_stream_store_upserts_latest_quote_and_appends_bars(tmp_path):
    db = tmp_path / "stream.sqlite3"
    store = StreamStore(db)
    quote = QuoteState(
        symbol="MES",
        contract="MESM6",
        bid=7443.25,
        ask=7443.5,
        last=7443.5,
        bid_size=8,
        ask_size=33,
        last_size=1,
        market_data_type=1,
        received_at_utc=datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc),
    )
    bar = Bar1s(
        symbol="MES",
        ts_utc=datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc),
        open=7443.25,
        high=7443.5,
        low=7443.25,
        close=7443.5,
        volume_proxy=3,
        bid=7443.25,
        ask=7443.5,
        spread=0.25,
    )

    store.upsert_latest_quote(quote)
    store.append_bar_1s(bar)

    loaded_quote = store.latest_quote("MES")
    loaded_bars = store.latest_bars_1s("MES", limit=10)

    assert loaded_quote is not None
    assert loaded_quote.as_dict() == quote.as_dict()
    assert [b.as_dict() for b in loaded_bars] == [bar.as_dict()]


def test_stream_store_is_idempotent_for_same_bar(tmp_path):
    store = StreamStore(tmp_path / "stream.sqlite3")
    bar = Bar1s(
        symbol="MES",
        ts_utc=datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc),
        open=1,
        high=2,
        low=1,
        close=2,
        volume_proxy=1,
        bid=1.75,
        ask=2,
        spread=0.25,
    )

    store.append_bar_1s(bar)
    store.append_bar_1s(bar)

    assert len(store.latest_bars_1s("MES", limit=10)) == 1
