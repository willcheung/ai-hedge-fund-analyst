from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trading_execution.stream_state import Bar1sBuilder, QuoteState, is_stale


def test_quote_state_serializes_json_safe_dict():
    ts = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)
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
        received_at_utc=ts,
    )

    assert quote.spread == 0.25
    assert quote.as_dict() == {
        "symbol": "MES",
        "contract": "MESM6",
        "bid": 7443.25,
        "ask": 7443.5,
        "last": 7443.5,
        "spread": 0.25,
        "bid_size": 8.0,
        "ask_size": 33.0,
        "last_size": 1.0,
        "market_data_type": 1,
        "received_at_utc": "2026-06-09T12:00:00+00:00",
    }


def test_quote_state_treats_non_positive_bid_ask_as_missing_book():
    ts = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)
    quote = QuoteState(
        symbol="MES",
        contract="MESM6",
        bid=-1.0,
        ask=-1.0,
        last=7508.75,
        bid_size=0,
        ask_size=0,
        last_size=1,
        market_data_type=1,
        received_at_utc=ts,
    )

    data = quote.as_dict()
    assert data["bid"] is None
    assert data["ask"] is None
    assert data["spread"] is None
    assert data["last"] == 7508.75


def test_is_stale_checks_quote_age():
    ts = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)
    quote = QuoteState(symbol="MES", contract="MESM6", bid=1, ask=2, last=1.5, received_at_utc=ts)

    assert is_stale(quote, now=ts + timedelta(seconds=4), max_age_seconds=5) is False
    assert is_stale(quote, now=ts + timedelta(seconds=6), max_age_seconds=5) is True


def test_bar_builder_aggregates_ticks_by_second():
    builder = Bar1sBuilder(symbol="MES")
    t0 = datetime(2026, 6, 9, 12, 0, 0, 100_000, tzinfo=timezone.utc)
    q1 = QuoteState(symbol="MES", contract="MESM6", bid=99.75, ask=100.0, last=100.0, last_size=2, received_at_utc=t0)
    q2 = QuoteState(symbol="MES", contract="MESM6", bid=100.25, ask=100.5, last=100.5, last_size=3, received_at_utc=t0 + timedelta(milliseconds=400))
    q3 = QuoteState(symbol="MES", contract="MESM6", bid=100.0, ask=100.25, last=100.25, last_size=1, received_at_utc=t0 + timedelta(seconds=1))

    assert builder.add(q1) is None
    assert builder.add(q2) is None
    completed = builder.add(q3)

    assert completed is not None
    assert completed.as_dict() == {
        "symbol": "MES",
        "ts_utc": "2026-06-09T12:00:00+00:00",
        "open": 100.0,
        "high": 100.5,
        "low": 100.0,
        "close": 100.5,
        "volume_proxy": 5.0,
        "bid": 100.25,
        "ask": 100.5,
        "spread": 0.25,
    }
    final_bar = builder.flush()
    assert final_bar is not None
    assert final_bar.close == 100.25
