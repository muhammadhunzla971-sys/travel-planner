"""TripState: the single shared object all agents read from and write to."""
from datetime import UTC, datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.allocation import BudgetAllocation
from app.models.messages import AgentMessage
from app.models.plan import CostLine, DayPlan, FlightOption, StayOption
from app.models.request import TripRequest


class TripStatus(str, Enum):
    pending = "pending"
    planning = "planning"
    negotiating = "negotiating"
    completed = "completed"
    completed_with_warnings = "completed_with_warnings"  # best feasible plan, something not met
    failed = "failed"


class Conflict(BaseModel):
    kind: str  # over_budget | late_arrival | too_far | overlap | ...
    description: str
    raised_by: str
    resolved: bool = False


class TripState(BaseModel):
    trip_id: str = Field(default_factory=lambda: uuid4().hex[:10])
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request: TripRequest
    status: TripStatus = TripStatus.pending

    allocation: BudgetAllocation | None = None

    flight_options: list[FlightOption] = Field(default_factory=list)
    selected_flight: FlightOption | None = None
    stay_options: list[StayOption] = Field(default_factory=list)
    selected_stay: StayOption | None = None
    days: list[DayPlan] = Field(default_factory=list)
    food_transport_estimate: float | None = None

    conflicts: list[Conflict] = Field(default_factory=list)
    messages: list[AgentMessage] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    iteration: int = 0
    max_iterations: int = 4

    # ---- messaging -------------------------------------------------------
    def post(self, message: AgentMessage) -> AgentMessage:
        message.round = self.iteration
        self.messages.append(message)
        return message

    def messages_for(self, agent: str) -> list[AgentMessage]:
        return [m for m in self.messages if m.to_agent.value == agent]

    # ---- negotiation rounds ---------------------------------------------
    def can_negotiate(self) -> bool:
        return self.iteration < self.max_iterations

    def next_round(self) -> int:
        self.iteration += 1
        return self.iteration

    # ---- costs -----------------------------------------------------------
    def cost_ledger(self) -> list[CostLine]:
        lines: list[CostLine] = []
        if self.selected_flight:
            f = self.selected_flight
            lines.append(CostLine(category="flights", description=f"{f.airline} {f.origin}-{f.destination}",
                                  amount=f.total_price, source=f.source))
        if self.selected_stay:
            s = self.selected_stay
            lines.append(CostLine(category="stays", description=s.name,
                                  amount=s.total_price, source=s.source))
        activities_total = round(sum(d.cost() for d in self.days), 2)
        if self.days:
            lines.append(CostLine(category="activities", description="Activities and entry fees",
                                  amount=activities_total))
        if self.food_transport_estimate is not None:
            lines.append(CostLine(category="food_transport", description="Food and local transport (estimate)",
                                  amount=self.food_transport_estimate))
        return lines

    def total_cost(self) -> float:
        return round(sum(line.amount for line in self.cost_ledger()), 2)

    def remaining_budget(self) -> float:
        return round(self.request.budget - self.total_cost(), 2)

    def is_within_budget(self) -> bool:
        return self.total_cost() <= self.request.budget
