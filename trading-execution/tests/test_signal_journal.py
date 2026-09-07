from __future__ import annotations

import json
from datetime import datetime, timezone

from trading_execution.signal_journal import append_signal, read_signals
from trading_execution.strategy import StrategySignal


def make_signal(state: str = "WAIT") -> StrategySignal:
    return StrategySignal(
        strategy="or-vwap",
        symbol="MES",
        state=state,  # type: ignore[arg-type]
        side=None,
        reason="test_reason",
        quote={"last": 100.0},
        levels={"vwap": 99.5},
    )


def test_append_signal_writes_jsonl_record(tmp_path):
    path = tmp_path / "signals.jsonl"
    signal = make_signal("SETUP_FORMING")

    record = append_signal(signal, path=path, stream_ok=True)

    assert record["signal"]["state"] == "SETUP_FORMING"
    assert record["stream_ok"] is True
    assert record["recorded_at"]
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["signal"]["reason"] == "test_reason"


def test_read_signals_returns_newest_limited_records(tmp_path):
    path = tmp_path / "signals.jsonl"
    append_signal(make_signal("WAIT"), path=path, stream_ok=True, recorded_at=datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc))
    append_signal(make_signal("ENTRY_READY"), path=path, stream_ok=True, recorded_at=datetime(2026, 6, 9, 12, 1, tzinfo=timezone.utc))
    append_signal(make_signal("EXIT_NOW"), path=path, stream_ok=True, recorded_at=datetime(2026, 6, 9, 12, 2, tzinfo=timezone.utc))

    records = read_signals(path=path, limit=2)

    assert [r["signal"]["state"] for r in records] == ["ENTRY_READY", "EXIT_NOW"]
