"""One pass of all agents (no negotiation yet): research -> propose -> critic.

This is the building block for the Step 5 orchestrator, which will repeat the
propose/critic cycle with constraints until the plan fits (max 4 rounds).
"""
import asyncio

from pydantic import BaseModel

from app.agents import (
    ActivitiesAgent,
    AgentContext,
    CriticAgent,
    FlightAgent,
    Proposal,
    Review,
    StayAgent,
)
from app.models.messages import AgentName, MessageType, make_message
from app.models.request import TripRequest
from app.models.state import TripState, TripStatus
from app.services.trip_data import TripData, gather_trip_data


class SinglePassResult(BaseModel):
    trip: TripState
    proposals: list[Proposal]
    review: Review
    total_cost: float
    remaining_budget: float
    within_budget: bool
    data_sources: dict[str, str]
    data_warnings: list[str]


async def run_single_pass(request: TripRequest, data: TripData | None = None) -> SinglePassResult:
    data = data or await gather_trip_data(request)
    alloc = data.allocation
    state = TripState(request=request, allocation=alloc, status=TripStatus.planning,
                      flight_options=data.flights, stay_options=data.stays,
                      food_transport_estimate=data.food_transport_estimate)
    ctx = AgentContext(request=request, data=data)

    # Flight and stay do not depend on each other -> run together.
    flight_p, stay_p = await asyncio.gather(FlightAgent().propose(ctx, alloc.flights),
                                            StayAgent().propose(ctx, alloc.stays))
    state.selected_flight, state.selected_stay = flight_p.flight, stay_p.stay
    ctx.flight = flight_p.flight  # activities need the flight times
    act_p = await ActivitiesAgent().propose(ctx, alloc.activities)
    state.days = act_p.days

    proposals = [flight_p, stay_p, act_p]
    for p in proposals:
        state.post(p.to_message())

    review = await CriticAgent().review(state, ctx)
    state.conflicts = review.conflicts
    state.warnings = list(dict.fromkeys(data.warnings + review.warnings))
    state.post(make_message(
        AgentName.critic, AgentName.orchestrator,
        MessageType.approval if review.approved else MessageType.constraint,
        payload={"approved": review.approved, "conflicts": [c.kind for c in review.conflicts],
                 "suggestions": [s.model_dump(mode="json") for s in review.suggestions]},
        reason=review.verdict))
    state.status = (TripStatus.completed if review.approved and not review.conflicts
                    else TripStatus.completed_with_warnings)

    return SinglePassResult(
        trip=state, proposals=proposals, review=review, total_cost=state.total_cost(),
        remaining_budget=state.remaining_budget(), within_budget=state.is_within_budget(),
        data_sources=data.sources, data_warnings=data.warnings)
