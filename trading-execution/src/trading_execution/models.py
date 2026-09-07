from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

Side = Literal["BUY", "SELL"]
EntryType = Literal["LIMIT", "STOP_LIMIT"]
BrokerName = Literal["ibkr"]


@dataclass(frozen=True)
class HumanApproval:
    approved: bool
    reviewer: str
    decided_at: str


@dataclass(frozen=True)
class TradeIntent:
    intent_id: str
    created_at: str
    mode: Literal["paper", "live"]
    broker: BrokerName
    symbol: str
    side: Side
    contracts: int
    entry_type: EntryType
    limit_price: float | None
    stop_price: float
    target_price: float | None
    max_loss_usd: float
    thesis: str
    invalidation: str | None
    expires_at: str
    requires_human_approval: bool
    human_approval: HumanApproval | None = None
    blocked_event_override: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TradeIntent":
        approval = data.get("human_approval")
        return cls(
            human_approval=HumanApproval(**approval) if approval else None,
            **{k: v for k, v in data.items() if k != "human_approval"},
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        now = now or datetime.now().astimezone()
        expires = datetime.fromisoformat(self.expires_at)
        return now > expires
