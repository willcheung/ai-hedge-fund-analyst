from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from trading_execution.config import state_root
from typing import Any

from trading_execution.strategy import StrategySignal

DEFAULT_SIGNAL_JOURNAL = state_root() / "signals.jsonl"


def append_signal(
    signal: StrategySignal,
    *,
    path: str | Path = DEFAULT_SIGNAL_JOURNAL,
    stream_ok: bool,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    recorded_at = recorded_at or datetime.now(timezone.utc)
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    record = {
        "recorded_at": recorded_at.astimezone(timezone.utc).isoformat(),
        "strategy": signal.strategy,
        "symbol": signal.symbol,
        "stream_ok": stream_ok,
        "signal": signal.as_dict(),
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def read_signals(*, path: str | Path = DEFAULT_SIGNAL_JOURNAL, limit: int = 100) -> list[dict[str, Any]]:
    src = Path(path)
    if not src.exists():
        return []
    lines = [line for line in src.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
    records: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records
