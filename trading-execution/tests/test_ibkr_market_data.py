from __future__ import annotations

from datetime import date, timedelta

from trading_execution.broker.ibkr_adapter import IBKRSettings
from trading_execution.broker.ibkr_market_data import IBKRMarketDataAdapter


class FakeContract:
    def __init__(self, symbol="MES", localSymbol="MESM6", conId=770561194, expiry="20260618"):
        self.symbol = symbol
        self.localSymbol = localSymbol
        self.conId = conId
        self.lastTradeDateOrContractMonth = expiry
        self.exchange = "CME"
        self.currency = "USD"
        self.multiplier = "5"
        self.tradingClass = "MES"

class FakeContractDetails:
    def __init__(self, contract):
        self.contract = contract

class FakeTicker:
    bid = 7437.5
    ask = 7437.75
    last = 7437.75
    close = 7416.0
    bidSize = 21
    askSize = 2
    lastSize = 2
    marketDataType = 1

class FakeFuture:
    def __init__(self, symbol, lastTradeDateOrContractMonth="", exchange="CME", currency="USD"):
        self.symbol = symbol
        self.lastTradeDateOrContractMonth = lastTradeDateOrContractMonth
        self.exchange = exchange
        self.currency = currency

class FakeIB:
    def __init__(self):
        self.connected = False
        self.cancelled = False

    def connect(self, host, port, clientId, timeout, readonly=True):
        self.connected = True
        return self

    def isConnected(self):
        return self.connected

    def disconnect(self):
        self.connected = False

    def reqContractDetails(self, contract):
        return [FakeContractDetails(FakeContract())]

    def qualifyContracts(self, contract):
        return [FakeContract()]

    def reqMarketDataType(self, market_data_type):
        self.market_data_type = market_data_type

    def reqMktData(self, contract, genericTickList, snapshot, regulatorySnapshot):
        return FakeTicker()

    def sleep(self, seconds):
        return None

    def cancelMktData(self, contract):
        self.cancelled = True


def test_mes_snapshot_resolves_front_contract_and_maps_realtime_l1(monkeypatch):
    monkeypatch.setattr(
        "trading_execution.broker.ibkr_market_data._ib_insync_import",
        lambda: ((FakeIB, FakeFuture, None, None), None),
    )

    snapshot = IBKRMarketDataAdapter(settings=IBKRSettings(port=4001)).snapshot("MES")

    assert snapshot["connected"] is True
    assert snapshot["symbol"] == "MES"
    assert snapshot["contract"] == "MESM6"
    assert snapshot["con_id"] == 770561194
    assert snapshot["bid"] == 7437.5
    assert snapshot["ask"] == 7437.75
    assert snapshot["last"] == 7437.75
    assert snapshot["spread"] == 0.25
    assert snapshot["delayed_or_unknown"] is False


def test_front_contract_skips_expiring_today_contract():
    today = date.today().strftime("%Y%m%d")
    next_expiry = (date.today() + timedelta(days=90)).strftime("%Y%m%d")

    class RolloverIB(FakeIB):
        def reqContractDetails(self, contract):
            return [
                FakeContractDetails(FakeContract(localSymbol="MESM6", conId=1, expiry=today)),
                FakeContractDetails(FakeContract(localSymbol="MESU6", conId=2, expiry=next_expiry)),
            ]

        def qualifyContracts(self, contract):
            return [contract]

    adapter = IBKRMarketDataAdapter(settings=IBKRSettings(port=4001))

    chosen = adapter._front_future(RolloverIB(), FakeFuture, "MES")

    assert chosen.localSymbol == "MESU6"
