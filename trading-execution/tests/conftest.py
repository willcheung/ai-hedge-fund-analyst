"""Real broker construction is forbidden in the unit suite.

Tests that exercise order logic explicitly replace the import seam with fakes.
OS-level network/process isolation remains required; this is defense in depth.
"""
import pytest


@pytest.fixture(autouse=True)
def forbid_real_broker(monkeypatch):
    def forbidden():
        pytest.fail("Unit tests must inject a fake IBKR implementation")
    monkeypatch.setattr("trading_execution.broker.ibkr_adapter._ib_insync_import", forbidden)
    monkeypatch.setattr("trading_execution.broker.ibkr_market_data._ib_insync_import", forbidden)
