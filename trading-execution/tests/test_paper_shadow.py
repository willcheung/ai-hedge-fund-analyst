from __future__ import annotations

from trading_execution.paper_shadow import shadow_report_from_signals


def signal_record(state, *, side=None, entry=None, stop=None, target=None, last=None, recorded_at="2026-06-09T12:00:00+00:00"):
    return {
        "recorded_at": recorded_at,
        "strategy": "or-vwap",
        "symbol": "MES",
        "stream_ok": True,
        "signal": {
            "strategy": "or-vwap",
            "symbol": "MES",
            "state": state,
            "side": side,
            "reason": "test",
            "entry_price": entry,
            "stop_price": stop,
            "target_price": target,
            "exit_reason": None,
            "quote": {"last": last},
        },
    }


def test_shadow_report_opens_and_closes_long_target_from_quotes():
    records = [
        signal_record("ENTRY_READY", side="BUY", entry=100.0, stop=99.0, target=102.0, last=100.0, recorded_at="2026-06-09T12:00:00+00:00"),
        signal_record("WAIT", last=101.0, recorded_at="2026-06-09T12:01:00+00:00"),
        signal_record("WAIT", last=102.25, recorded_at="2026-06-09T12:02:00+00:00"),
    ]

    report = shadow_report_from_signals(records)

    assert report["closed_trades_count"] == 1
    assert report["open_position"] is None
    trade = report["closed_trades"][0]
    assert trade["side"] == "BUY"
    assert trade["exit_reason"] == "target_hit"
    assert trade["r_multiple"] == 2.0


def test_shadow_report_opens_and_closes_short_stop_from_quotes():
    records = [
        signal_record("ENTRY_READY", side="SELL", entry=100.0, stop=101.0, target=98.0, last=100.0),
        signal_record("WAIT", last=101.25, recorded_at="2026-06-09T12:01:00+00:00"),
    ]

    report = shadow_report_from_signals(records)

    assert report["closed_trades_count"] == 1
    trade = report["closed_trades"][0]
    assert trade["exit_reason"] == "stop_hit"
    assert trade["r_multiple"] == -1.0


def test_shadow_report_keeps_position_open_when_no_exit():
    records = [signal_record("ENTRY_READY", side="BUY", entry=100.0, stop=99.0, target=102.0, last=100.0)]

    report = shadow_report_from_signals(records)

    assert report["closed_trades_count"] == 0
    assert report["open_position"]["side"] == "BUY"
