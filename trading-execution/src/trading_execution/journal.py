from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any

from .models import TradeIntent
from .risk import RiskDecision


def append_audit(event: dict[str, Any], audit_log: str | Path) -> None:
    path = Path(audit_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {"recorded_at": datetime.now(timezone.utc).isoformat(), **event}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def write_trade_journal(intent: TradeIntent, decision: RiskDecision, journal_dir: str | Path) -> Path:
    path = Path(journal_dir)
    path.mkdir(parents=True, exist_ok=True)
    out = path / f"{intent.intent_id}.json"
    payload = {
        "intent": asdict(intent),
        "risk_decision": asdict(decision),
        "status": "APPROVED_FOR_PAPER_EXECUTION" if decision.approved else "REJECTED_BY_RISK_GATE",
        "postmortem": None,
        "lessons": [],
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out
