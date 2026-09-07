from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    description: str
    exchange: str
    currency: str
    multiplier: float
    dollars_per_point: float
    min_tick: float
    tick_value: float
    max_contracts: int
    data_enabled: bool
    trading_enabled: bool
    primary_algo_target: bool = False


def normalize_symbol(symbol: str) -> str:
    upper = str(symbol).upper().strip()
    for prefix in ("MES", "MNQ", "MGC", "ES", "NQ", "GC"):
        if upper.startswith(prefix):
            return prefix
    return upper


class InstrumentRegistry:
    def __init__(self, instruments: dict[str, InstrumentSpec]) -> None:
        self._instruments = instruments

    @classmethod
    def from_config_path(cls, path: str | Path) -> "InstrumentRegistry":
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        raw = payload.get("instruments", {})
        instruments = {
            normalize_symbol(symbol): InstrumentSpec(symbol=normalize_symbol(symbol), **values)
            for symbol, values in raw.items()
        }
        return cls(instruments)

    def get(self, symbol: str) -> InstrumentSpec | None:
        return self._instruments.get(normalize_symbol(symbol))

    def require(self, symbol: str) -> InstrumentSpec:
        normalized = normalize_symbol(symbol)
        spec = self.get(normalized)
        if spec is None:
            raise KeyError(f"Instrument not configured: {normalized}")
        return spec

    def allowed_for_data(self) -> list[str]:
        return [symbol for symbol, spec in self._instruments.items() if spec.data_enabled]

    def allowed_for_trading(self) -> list[str]:
        return [symbol for symbol, spec in self._instruments.items() if spec.trading_enabled]

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {symbol: spec.__dict__.copy() for symbol, spec in self._instruments.items()}
