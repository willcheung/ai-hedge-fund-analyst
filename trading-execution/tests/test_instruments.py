from __future__ import annotations

import pytest

from trading_execution.instruments import InstrumentRegistry, normalize_symbol


@pytest.fixture
def instrument_config(tmp_path):
    # Synthetic loader fixture, not copied account/production configuration.
    import yaml
    instruments = {}
    for symbol, point, cap in [("MES", 5, 1), ("ES", 50, 0), ("NQ", 20, 0)]:
        instruments[symbol] = dict(description="Micro E-mini S&P 500 futures" if symbol == "MES" else "Synthetic test instrument",
            exchange="CME", currency="USD", multiplier=point, dollars_per_point=point,
            min_tick=0.25, tick_value=point * 0.25, max_contracts=cap,
            data_enabled=True, trading_enabled=False)
    path = tmp_path / "instruments.yaml"
    path.write_text(yaml.safe_dump({"instruments": instruments}))
    return path


def test_mes_is_initial_primary_allowed_instrument(instrument_config):
    registry = InstrumentRegistry.from_config_path(instrument_config)
    mes = registry.require("MES")

    assert mes.symbol == "MES"
    assert mes.description == "Micro E-mini S&P 500 futures"
    assert mes.dollars_per_point == pytest.approx(5.0)
    assert mes.min_tick == pytest.approx(0.25)
    assert mes.tick_value == pytest.approx(1.25)
    assert mes.max_contracts == 1
    assert mes.trading_enabled is False
    assert mes.data_enabled is True


def test_full_size_equity_index_futures_are_disabled(instrument_config):
    registry = InstrumentRegistry.from_config_path(instrument_config)

    assert registry.require("ES").max_contracts == 0
    assert registry.require("NQ").max_contracts == 0
    assert registry.require("MES").max_contracts == 1


def test_symbol_normalization_handles_front_month_aliases():
    assert normalize_symbol("MES") == "MES"
    assert normalize_symbol("MESM6") == "MES"
    assert normalize_symbol("MNQZ26") == "MNQ"
    assert normalize_symbol("MGCmain") == "MGC"
