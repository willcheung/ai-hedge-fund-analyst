from __future__ import annotations

import importlib.util
from unittest.mock import patch
from pathlib import Path


def load_trading_status_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "trading_status.py"
    spec = importlib.util.spec_from_file_location("trading_status", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with patch.dict("os.environ", {"ANALYST_EXECUTION_ROOT": "/tmp/synthetic-execution", "ANALYST_HERMES_HOME": "/tmp/synthetic-hermes"}):
        spec.loader.exec_module(module)
    return module


def test_quote_quality_rejects_ibkr_negative_bid_ask_sentinel():
    mod = load_trading_status_module()

    ok, reason = mod.quote_quality({"bid": -1.0, "ask": -1.0, "last": 7508.75, "market_data_type": 1})

    assert ok is False
    assert reason == "invalid_bid_ask"


def test_quote_quality_accepts_tradeable_realtime_book():
    mod = load_trading_status_module()

    ok, reason = mod.quote_quality({"bid": 7508.5, "ask": 7508.75, "last": 7508.75, "market_data_type": 1})

    assert ok is True
    assert reason == "ok"
