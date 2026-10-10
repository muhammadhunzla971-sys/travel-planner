"""Shared pieces for all agents: context, constraints, proposals, LLM helper."""
import json
import logging
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.llm.client import LLMUnavailable, chat_json
from app.models.messages import AgentMessage, AgentName, MessageType, make_message
from app.models.plan import DayPlan, FlightOption, StayOption
from app.models.request import TripRequest
from app.services.trip_data import TripData

log = logging.getLogger(__name__)


class Constraints(BaseModel):
    """What the orchestrator/critic can ask an agent to respect on its next try."""
    max_price: float | None = Field(default=None, ge=0, description="Hard cap for this agent")
    max_stops: int | None = Field(default=None, ge=0)
    avoid_late_arrival: bool = False
    free_only: bool = False  # activities: only free places
    note: str = ""


class Proposal(BaseModel):
    agent: AgentName
    summary: str
    cost: float
    cap: float
    within_cap: bool
    reason: str
    used_llm: bool = False
    considered: int = 0
    flight: FlightOption | None = None
    stay: StayOption | None = None
    days: list[DayPlan] = Field(default_factory=list)

    def choice_id(self) -> str | None:
        if self.flight:
            return self.flight.id
        if self.stay:
            return self.stay.id
        return None

    def to_message(self, to: AgentName = AgentName.orchestrator,
                   type: MessageType = MessageType.proposal) -> AgentMessage:
        return make_message(self.agent, to, type, payload={
            "choice_id": self.choice_id(), "cost": self.cost, "cap": self.cap,
            "within_cap": self.within_cap, "summary": self.summary,
        }, reason=self.reason)


@dataclass
class AgentContext:
    request: TripRequest
    data: TripData
    flight: FlightOption | None = None  # filled in once a flight has been chosen


class BaseAgent:
    name: ClassVar[AgentName]


async def ask_llm(system: str, payload: dict[str, Any], *, max_tokens: int = 1200) -> dict[str, Any] | None:
    """Ask the LLM; return None on ANY problem so callers use their rule-based result."""
    try:
        return await chat_json(system, json.dumps(payload, ensure_ascii=False, default=str),
                               max_tokens=max_tokens)
    except LLMUnavailable as exc:
        log.info("LLM not used: %s", exc)
        return None
    except Exception:  # never let the LLM layer crash an agent
        log.exception("unexpected LLM error")
        return None


def clean_text(value: Any, limit: int) -> str:
    """LLM text -> short single-line string (or '' if it is not text)."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def money(amount: float, currency: str) -> str:
    return f"{amount:,.0f} {currency}"
