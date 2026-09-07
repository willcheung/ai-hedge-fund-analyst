from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from trading_execution.stream_state import Bar1s, QuoteState

ET = ZoneInfo("America/New_York")
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _as_et(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=ZoneInfo("UTC"))
    return ts.astimezone(ET)


def _rth_open_for(now: datetime) -> datetime:
    now_et = _as_et(now)
    return datetime.combine(now_et.date(), RTH_OPEN, tzinfo=ET)


def _rth_close_for(now: datetime) -> datetime:
    now_et = _as_et(now)
    return datetime.combine(now_et.date(), RTH_CLOSE, tzinfo=ET)


def _in_range(bar: Bar1s, start_et: datetime, end_et: datetime) -> bool:
    ts = _as_et(bar.ts_utc)
    return start_et <= ts < end_et


def _high(bars: Iterable[Bar1s]) -> float | None:
    values = [bar.high for bar in bars]
    return max(values) if values else None


def _low(bars: Iterable[Bar1s]) -> float | None:
    values = [bar.low for bar in bars]
    return min(values) if values else None


@dataclass(frozen=True)
class MESLevels:
    symbol: str
    calculated_at_utc: str
    bars_used: int
    latest_quote: dict[str, Any] | None
    vwap: float | None
    last_vs_vwap: float | None
    or5_high: float | None
    or5_low: float | None
    or15_high: float | None
    or15_low: float | None
    or30_high: float | None
    or30_low: float | None
    overnight_high: float | None
    overnight_low: float | None
    prior_rth_high: float | None = None
    prior_rth_low: float | None = None
    prior_rth_close: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def calculate_mes_levels(
    bars: list[Bar1s],
    *,
    latest_quote: QuoteState | None,
    now: datetime | None = None,
) -> MESLevels:
    """Calculate the minimal MES levels needed for the first strategy.

    This intentionally avoids a full market-session framework. It uses the current
    ET calendar date, standard 09:30-16:00 RTH, and whatever stream bars are already
    available in SQLite.
    """

    now = now or (latest_quote.received_at_utc if latest_quote else (bars[-1].ts_utc if bars else datetime.now(tz=ZoneInfo("UTC"))))
    bars = sorted(bars, key=lambda b: b.ts_utc)
    rth_open = _rth_open_for(now)
    rth_close = _rth_close_for(now)

    rth_bars = [bar for bar in bars if _in_range(bar, rth_open, rth_close)]
    total_weight = sum(max(float(bar.volume_proxy or 0.0), 0.0) for bar in rth_bars)
    if rth_bars and total_weight > 0:
        vwap = sum(bar.close * max(float(bar.volume_proxy or 0.0), 0.0) for bar in rth_bars) / total_weight
    elif rth_bars:
        vwap = sum(bar.close for bar in rth_bars) / len(rth_bars)
    else:
        vwap = None

    def opening_range(minutes: int) -> tuple[float | None, float | None]:
        end = rth_open + timedelta(minutes=minutes)
        subset = [bar for bar in bars if _in_range(bar, rth_open, end)]
        return _high(subset), _low(subset)

    or5_high, or5_low = opening_range(5)
    or15_high, or15_low = opening_range(15)
    or30_high, or30_low = opening_range(30)

    overnight_bars = [
        bar
        for bar in bars
        if _as_et(bar.ts_utc).date() == rth_open.date() and _as_et(bar.ts_utc) < rth_open
    ]

    last = latest_quote.last if latest_quote else (bars[-1].close if bars else None)
    last_vs_vwap = (last - vwap) if last is not None and vwap is not None else None

    return MESLevels(
        symbol="MES",
        calculated_at_utc=now.astimezone(ZoneInfo("UTC")).isoformat(),
        bars_used=len(bars),
        latest_quote=latest_quote.as_dict() if latest_quote else None,
        vwap=_round(vwap),
        last_vs_vwap=_round(last_vs_vwap),
        or5_high=_round(or5_high),
        or5_low=_round(or5_low),
        or15_high=_round(or15_high),
        or15_low=_round(or15_low),
        or30_high=_round(or30_high),
        or30_low=_round(or30_low),
        overnight_high=_round(_high(overnight_bars)),
        overnight_low=_round(_low(overnight_bars)),
    )
