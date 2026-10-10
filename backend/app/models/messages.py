"""Message protocol: how agents talk to each other.

Example negotiation:
  flight -> orchestrator : proposal           (flight uses 45% of budget)
  orchestrator -> flight : constraint         (cap flights at 35%)
  flight -> orchestrator : counter_proposal   (cheaper dates / 1 stop)
  orchestrator -> flight : approval
"""
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AgentName(str, Enum):
    orchestrator = "orchestrator"
    flight = "flight"
    stay = "stay"
    activities = "activities"
    critic = "critic"


class MessageType(str, Enum):
    request = "request"
    proposal = "proposal"
    counter_proposal = "counter_proposal"
    constraint = "constraint"
    approval = "approval"


class AgentMessage(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    from_agent: AgentName
    to_agent: AgentName
    type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    round: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def make_message(
    from_agent: AgentName,
    to_agent: AgentName,
    type: MessageType,
    payload: dict[str, Any] | None = None,
    reason: str = "",
    round: int = 0,
) -> AgentMessage:
    return AgentMessage(
        from_agent=from_agent,
        to_agent=to_agent,
        type=type,
        payload=payload or {},
        reason=reason,
        round=round,
    )
