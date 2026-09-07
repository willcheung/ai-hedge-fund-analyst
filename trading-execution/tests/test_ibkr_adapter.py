from __future__ import annotations

from datetime import date, timedelta

import pytest

from trading_execution.broker.ibkr_adapter import IBKRAdapter, IBKRSafetyError, IBKRSettings
from trading_execution.models import TradeIntent


class FakeContract:
    def __init__(self, symbol="MES", localSymbol="MESM6", secType="FUT", exchange="CME", currency="USD", expiry=""):
        self.symbol = symbol
        self.localSymbol = localSymbol
        self.secType = secType
        self.exchange = exchange
        self.currency = currency
        self.lastTradeDateOrContractMonth = expiry


class FakePortfolioItem:
    def __init__(self):
        self.contract = FakeContract()
        self.position = 1
        self.marketPrice = 7437.5
        self.marketValue = 37187.5
        self.averageCost = 7420.0
        self.unrealizedPNL = 87.5
        self.realizedPNL = 0.0


class FakeTrade:
    def __init__(self):
        self.contract = FakeContract()
        self.order = type(
            "Order",
            (),
            {
                "orderId": 123,
                "action": "SELL",
                "orderType": "STP",
                "totalQuantity": 1,
                "auxPrice": 7425.0,
                "lmtPrice": 0.0,
            },
        )()
        self.orderStatus = type(
            "OrderStatus", (), {"status": "Submitted", "filled": 0, "remaining": 1}
        )()


class FakeContractDetails:
    def __init__(self, contract):
        self.contract = contract


class FakeOrder:
    def __init__(self, action, totalQuantity, price):
        self.action = action
        self.totalQuantity = totalQuantity
        self.orderId = 0
        self.parentId = 0
        self.transmit = True
        self.lmtPrice = 0.0
        self.auxPrice = 0.0
        if self.__class__.__name__ == "FakeLimitOrder":
            self.orderType = "LMT"
            self.lmtPrice = price
        else:
            self.orderType = "STP"
            self.auxPrice = price


class FakeLimitOrder(FakeOrder):
    pass


class FakeStopOrder(FakeOrder):
    pass


class FakeClient:
    def __init__(self):
        self.next_id = 1000

    def getReqId(self):
        self.next_id += 1
        return self.next_id


class FakeIB:
    def __init__(self):
        self.connected = False
        self.connect_readonly_values = []
        self.placed_orders = []
        self.cancelled_orders = []
        self.client = FakeClient()

    def connect(self, host, port, clientId, timeout, readonly=True):
        self.connected = True
        self.connect_readonly_values.append(readonly)
        return self

    def isConnected(self):
        return self.connected

    def disconnect(self):
        self.connected = False

    def reqCurrentTime(self):
        return "2026-06-09 08:10:05+00:00"

    def managedAccounts(self):
        return ["SYNTHETIC_ACCOUNT"]

    def portfolio(self):
        return [FakePortfolioItem()]

    def openTrades(self):
        return [FakeTrade()]

    def reqContractDetails(self, contract):
        return [FakeContractDetails(FakeContract(localSymbol="MESM6"))]

    def qualifyContracts(self, contract):
        return [contract]

    def placeOrder(self, contract, order):
        trade = type(
            "PlacedTrade",
            (),
            {"contract": contract, "order": order, "orderStatus": type("OrderStatus", (), {"status": "Submitted"})()},
        )()
        self.placed_orders.append((contract, order))
        return trade

    def cancelOrder(self, order):
        self.cancelled_orders.append(order)

    def sleep(self, _seconds):
        return None


def approved_mes_intent() -> TradeIntent:
    return TradeIntent.from_dict(
        {
            "intent_id": "TI-20990101-synth1",
            "created_at": "2026-06-05T13:30:00+00:00",
            "mode": "paper",
            "broker": "ibkr",
            "symbol": "MES",
            "side": "BUY",
            "contracts": 1,
            "entry_type": "LIMIT",
            "limit_price": 5400.0,
            "stop_price": 5390.0,
            "target_price": 5420.0,
            "max_loss_usd": 50.0,
            "thesis": "VWAP reclaim with defined invalidation",
            "invalidation": "Lose VWAP reclaim level",
            "expires_at": "2099-06-05T14:00:00+00:00",
            "requires_human_approval": True,
            "human_approval": {
                "approved": True,
                "reviewer": "synthetic-reviewer",
                "decided_at": "2099-01-01T00:01:00+00:00",
            },
        }
    )


def test_ibkr_settings_default_to_paper_gateway():
    settings = IBKRSettings.from_env({})

    assert settings.host == "127.0.0.1"
    assert settings.port == 7497
    assert settings.client_id == 77
    assert settings.mode == "paper"
    assert settings.trading_enabled is False
    assert settings.live_risk_acknowledged is False


def test_order_placement_enabled_requires_explicit_live_risk_acknowledgement():
    adapter = IBKRAdapter(settings=IBKRSettings(mode="live", trading_enabled=True, readonly=False, account="SYNTHETIC_ACCOUNT"))

    assert adapter._safe_base()["order_placement_enabled"] is False


def test_preview_order_requires_ibkr_broker_and_never_places_order():
    adapter = IBKRAdapter(settings=IBKRSettings(trading_enabled=False))
    preview = adapter.preview_order(approved_mes_intent())

    assert preview["preview_only"] is True
    assert preview["broker"] == "ibkr"
    assert preview["symbol"] == "MES"
    assert preview["order_placement_enabled"] is False
    assert preview["bracket_required"] is True


def test_preview_rejects_non_ibkr_intent():
    payload = approved_mes_intent().__dict__.copy()
    payload["broker"] = "webull"
    payload["human_approval"] = {
        "approved": True,
        "reviewer": "synthetic-reviewer",
        "decided_at": "2099-01-01T00:01:00+00:00",
    }
    intent = TradeIntent.from_dict(payload)

    with pytest.raises(IBKRSafetyError):
        IBKRAdapter().preview_order(intent)


def test_health_reports_disconnected_without_gateway_in_safe_mode(monkeypatch):
    monkeypatch.setattr("trading_execution.broker.ibkr_adapter._ib_insync_import",
                        lambda: (None, "synthetic adapter unavailable"))
    adapter = IBKRAdapter(settings=IBKRSettings(connect_timeout=0.01))
    health = adapter.health()

    assert health["broker"] == "ibkr"
    assert health["mode"] == "paper"
    assert health["order_placement_enabled"] is False
    assert "connected" in health


def test_health_includes_managed_accounts_without_exposing_secrets(monkeypatch):
    monkeypatch.setattr(
        "trading_execution.broker.ibkr_adapter._ib_insync_import",
        lambda: ((FakeIB, None, None, None), None),
    )
    health = IBKRAdapter(settings=IBKRSettings(port=4001)).health()

    assert health["connected"] is True
    assert health["managed_accounts_count"] == 1
    assert health["managed_accounts"] == ["SYNTHETIC_ACCOUNT"]


def test_list_positions_maps_ibkr_portfolio_items(monkeypatch):
    monkeypatch.setattr(
        "trading_execution.broker.ibkr_adapter._ib_insync_import",
        lambda: ((FakeIB, None, None, None), None),
    )

    positions = IBKRAdapter(settings=IBKRSettings(port=4001)).list_positions()

    assert positions == [
        {
            "symbol": "MESM6",
            "root_symbol": "MES",
            "sec_type": "FUT",
            "exchange": "CME",
            "currency": "USD",
            "quantity": 1.0,
            "market_price": 7437.5,
            "market_value": 37187.5,
            "average_cost": 7420.0,
            "unrealized_pnl": 87.5,
            "realized_pnl": 0.0,
        }
    ]


def test_list_open_orders_maps_ibkr_open_trades(monkeypatch):
    monkeypatch.setattr(
        "trading_execution.broker.ibkr_adapter._ib_insync_import",
        lambda: ((FakeIB, None, None, None), None),
    )

    orders = IBKRAdapter(settings=IBKRSettings(port=4001)).list_open_orders()

    assert orders == [
        {
            "symbol": "MESM6",
            "root_symbol": "MES",
            "sec_type": "FUT",
            "exchange": "CME",
            "order_id": 123,
            "side": "SELL",
            "order_type": "STP",
            "quantity": 1.0,
            "status": "Submitted",
            "filled": 0.0,
            "remaining": 1.0,
            "stop_price": 7425.0,
            "limit_price": None,
        }
    ]


def test_place_bracket_order_requires_trading_enabled():
    adapter = IBKRAdapter(settings=IBKRSettings(mode="live", trading_enabled=False, readonly=True, account="SYNTHETIC_ACCOUNT"))

    with pytest.raises(IBKRSafetyError, match="order placement disabled"):
        adapter.place_bracket_order(approved_mes_intent())


def test_place_bracket_order_requires_live_risk_acknowledgement():
    payload = approved_mes_intent().__dict__.copy()
    payload["mode"] = "live"
    payload["human_approval"] = {
        "approved": True,
        "reviewer": "synthetic-reviewer",
        "decided_at": "2099-01-01T00:01:00+00:00",
    }
    intent = TradeIntent.from_dict(payload)
    adapter = IBKRAdapter(settings=IBKRSettings(mode="live", trading_enabled=True, readonly=False, account="SYNTHETIC_ACCOUNT"))

    with pytest.raises(IBKRSafetyError, match="live risk acknowledgement"):
        adapter.place_bracket_order(intent)


def test_order_adapter_front_contract_skips_expiring_today_contract():
    today = date.today().strftime("%Y%m%d")
    next_expiry = (date.today() + timedelta(days=90)).strftime("%Y%m%d")

    class RolloverIB(FakeIB):
        def reqContractDetails(self, contract):
            return [
                FakeContractDetails(FakeContract(localSymbol="MESM6", expiry=today)),
                FakeContractDetails(FakeContract(localSymbol="MESU6", expiry=next_expiry)),
            ]

    chosen = IBKRAdapter()._front_future(RolloverIB(), FakeContract, "MES")

    assert chosen.localSymbol == "MESU6"


def test_place_bracket_order_submits_entry_stop_and_target_when_armed(monkeypatch):
    fake_ib = FakeIB()

    monkeypatch.setattr(
        "trading_execution.broker.ibkr_adapter._ib_insync_import",
        lambda: ((lambda: fake_ib, FakeContract, FakeLimitOrder, FakeStopOrder), None),
    )
    payload = approved_mes_intent().__dict__.copy()
    payload["mode"] = "live"
    payload["contracts"] = 2
    payload["human_approval"] = {
        "approved": True,
        "reviewer": "synthetic-reviewer",
        "decided_at": "2099-01-01T00:01:00+00:00",
    }
    intent = TradeIntent.from_dict(payload)

    result = IBKRAdapter(
        settings=IBKRSettings(mode="live", trading_enabled=True, readonly=False, account="SYNTHETIC_ACCOUNT", live_risk_acknowledged=True)
    ).place_bracket_order(intent)

    assert fake_ib.connect_readonly_values == [False]
    assert result["placed"] is True
    entry_order = fake_ib.placed_orders[0][1]
    stop_order = fake_ib.placed_orders[1][1]
    target_order = fake_ib.placed_orders[2][1]
    assert entry_order.orderId
    assert stop_order.parentId == entry_order.orderId
    assert target_order.parentId == entry_order.orderId
    assert result["orders"] == [
        {"role": "entry", "side": "BUY", "order_type": "LMT", "quantity": 2, "limit_price": 5400.0, "stop_price": None, "transmit": False},
        {"role": "stop", "side": "SELL", "order_type": "STP", "quantity": 2, "limit_price": None, "stop_price": 5390.0, "transmit": False},
        {"role": "target", "side": "SELL", "order_type": "LMT", "quantity": 2, "limit_price": 5420.0, "stop_price": None, "transmit": True},
    ]
