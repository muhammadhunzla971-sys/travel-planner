"""Pure helpers for the negotiation: who gives up how much when the plan is too expensive,
and the planned-vs-actual budget table. No I/O, so it is easy to test."""
import math

from pydantic import BaseModel

from app.models.messages import AgentName
from app.models.state import TripState

# Who gives way first when the total is over budget.
# Activities go first: their cost can shrink in small steps (drop a paid place) and cutting them
# hurts least. Only if that is not enough do the stay and the flight share the rest, in
# proportion to these weights (hotels and flights come in big discrete steps, so they are
# touched last). Shares add up to 1.0.
FLEXIBILITY: dict[AgentName, float] = {
    AgentName.activities: 0.45,
    AgentName.stay: 0.35,
    AgentName.flight: 0.20,
}
FIRST_TO_GIVE = AgentName.activities


def _down(value: float) -> float:
    """Round DOWN to cents so a target never ends up a cent above what was meant."""
    return math.floor(value * 100 + 1e-9) / 100


def squeeze_targets(costs: dict[AgentName, float], floors: dict[AgentName, float],
                    overage: float) -> tuple[dict[AgentName, float], float]:
    """Cut `overage` from the agents' current costs.

    Phase 1: activities give as much as they can (down to their floor). Phase 2: stay and
    flight share what is left in proportion to FLEXIBILITY. Nobody goes below their floor (the
    cheapest thing they could still propose). Returns (new max prices, amount that could NOT
    be cut). unmet > 0 means it is impossible without relaxing something.
    """
    targets = dict(costs)
    remaining = max(overage, 0.0)

    if FIRST_TO_GIVE in targets and remaining > 0.005:
        cut = min(remaining, max(targets[FIRST_TO_GIVE] - floors.get(FIRST_TO_GIVE, 0.0), 0.0))
        targets[FIRST_TO_GIVE] -= cut
        remaining -= cut

    weights = {a: w for a, w in FLEXIBILITY.items() if a != FIRST_TO_GIVE}
    for _ in range(12):  # each pass either finishes or exhausts at least one agent
        if remaining <= 0.005:
            break
        active = {a: w for a, w in weights.items()
                  if a in targets and targets[a] - floors.get(a, 0.0) > 0.005}
        if not active:
            break
        weight_sum = sum(active.values())
        cut_now = 0.0
        for agent, weight in active.items():
            cut = min(remaining * weight / weight_sum, targets[agent] - floors.get(agent, 0.0))
            targets[agent] = targets[agent] - cut
            cut_now += cut
        remaining -= cut_now
    return {a: _down(v) for a, v in targets.items()}, round(max(remaining, 0.0), 2)


class BreakdownLine(BaseModel):
    category: str
    planned: float   # the starting share of the budget
    actual: float    # what the final plan really costs
    delta: float     # actual - planned (positive = went over its share)


class BudgetBreakdown(BaseModel):
    currency: str
    budget: float
    total_cost: float
    remaining: float
    within_budget: bool
    lines: list[BreakdownLine]


def build_breakdown(state: TripState) -> BudgetBreakdown:
    alloc = state.allocation
    spent = {
        "flights": state.selected_flight.total_price if state.selected_flight else 0.0,
        "stays": state.selected_stay.total_price if state.selected_stay else 0.0,
        "activities": round(sum(d.cost() for d in state.days), 2),
        "food_transport": state.food_transport_estimate or 0.0,
    }
    total = state.total_cost()
    remaining = state.remaining_budget()
    planned = alloc.amounts() if alloc else {}
    lines = [BreakdownLine(category=c, planned=planned.get(c, 0.0), actual=round(a, 2),
                           delta=round(a - planned.get(c, 0.0), 2)) for c, a in spent.items()]
    buffer_planned = planned.get("buffer", 0.0)
    lines.append(BreakdownLine(category="unspent", planned=buffer_planned, actual=max(remaining, 0.0),
                               delta=round(max(remaining, 0.0) - buffer_planned, 2)))
    return BudgetBreakdown(currency=state.request.currency, budget=state.request.budget,
                           total_cost=total, remaining=remaining, within_budget=total <= state.request.budget,
                           lines=lines)
