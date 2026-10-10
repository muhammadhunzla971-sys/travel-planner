"""Critic Agent: checks a draft plan and reports conflicts the orchestrator must resolve.

All checks are deterministic code (so a hallucinating LLM can never approve a bad plan).
The LLM only turns the findings into a short, readable verdict.
"""
from pydantic import BaseModel, Field

from app.agents.activities import is_rainy
from app.agents.base import (
    AgentContext,
    BaseAgent,
    Constraints,
    ask_llm,
    clean_text,
    money,
)
from app.agents.flight import is_late_arrival
from app.agents.prompts import CRITIC_SYSTEM
from app.models.messages import AgentName
from app.models.state import Conflict, TripState

# Conflicts that make a plan "not approved" - negotiation should try to fix them.
BLOCKING = {"over_budget", "late_arrival", "overlap", "outside_window"}
UNDERSPEND_SHARE = 0.35
FLIGHT_HEAVY_SHARE = 0.55


class Suggestion(BaseModel):
    target: AgentName
    constraints: Constraints
    reason: str


class Review(BaseModel):
    approved: bool
    conflicts: list[Conflict] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    verdict: str = ""
    advice: list[str] = Field(default_factory=list)
    used_llm: bool = False
    total_cost: float = 0.0
    budget: float = 0.0


class CriticAgent(BaseAgent):
    name = AgentName.critic

    # ---- deterministic checks -------------------------------------------
    def check(self, state: TripState, ctx: AgentContext) -> Review:
        req = state.request
        cur = req.currency
        conflicts: list[Conflict] = []
        suggestions: list[Suggestion] = []
        warnings: list[str] = []

        def conflict(kind: str, text: str) -> None:
            conflicts.append(Conflict(kind=kind, description=text, raised_by=self.name.value))

        total = state.total_cost()
        alloc = state.allocation
        flight, stay = state.selected_flight, state.selected_stay

        # 1. Is the trip affordable at all? (cheapest flight + cheapest stay + food/transport)
        cheapest_flight = min((f.total_price for f in ctx.data.flights), default=0.0)
        cheapest_stay = min((s.total_price for s in ctx.data.stays), default=0.0)
        floor = round(cheapest_flight + cheapest_stay + (state.food_transport_estimate or 0.0), 2)
        infeasible = floor > req.budget
        if infeasible:
            conflict("infeasible",
                     f"Even the cheapest flight, stay and food/transport cost about {money(floor, cur)}, "
                     f"above the budget of {money(req.budget, cur)}. Increase the budget to at least "
                     f"{money(floor, cur)}, shorten the trip or choose a closer destination.")

        # 2. Total over budget (only when it can be fixed by choosing differently)
        if total > req.budget and not infeasible:
            over = round(total - req.budget, 2)
            conflict("over_budget", f"The plan costs {money(total, cur)}, which is {money(over, cur)} "
                                    f"over the budget of {money(req.budget, cur)}.")
            if alloc is not None:
                spend = {AgentName.flight: flight.total_price if flight else 0.0,
                         AgentName.stay: stay.total_price if stay else 0.0,
                         AgentName.activities: round(sum(d.cost() for d in state.days), 2)}
                cap = {AgentName.flight: alloc.flights, AgentName.stay: alloc.stays,
                       AgentName.activities: alloc.activities}
                over_cap = {a: spend[a] - cap[a] for a in spend if spend[a] > cap[a] + 1e-9}
                for agent, extra in sorted(over_cap.items(), key=lambda kv: -kv[1]):
                    suggestions.append(Suggestion(
                        target=agent, constraints=Constraints(max_price=round(cap[agent], 2)),
                        reason=f"{agent.value} is {money(extra, cur)} over its share of the budget."))
                if not suggestions:  # nobody is over their share: squeeze the biggest cost
                    biggest = max(spend, key=lambda a: spend[a])
                    suggestions.append(Suggestion(
                        target=biggest,
                        constraints=Constraints(max_price=round(max(spend[biggest] - over, 0.0), 2)),
                        reason=f"Reduce {biggest.value} by {money(over, cur)} to fit the budget."))

        # 3. Late-night arrival
        if flight is not None and is_late_arrival(flight):
            alternatives = [f for f in ctx.data.flights if not is_late_arrival(f)]
            when = flight.arrive_at.strftime("%H:%M")
            if alternatives and not infeasible:  # when nothing fits the budget, day flights cost more
                conflict("late_arrival", f"The flight lands at {when}, in the middle of the night.")
                suggestions.append(Suggestion(
                    target=AgentName.flight, constraints=Constraints(avoid_late_arrival=True),
                    reason="Choose a flight that lands during the day."))
            else:
                warnings.append(f"The flight lands at {when} (night); "
                                f"{'a daytime flight would cost more' if alternatives else 'no daytime alternative was found'}.")

        # 4. Schedule problems
        weather = {w.date: w for w in ctx.data.weather}
        for day in state.days:
            if day.has_overlaps():
                conflict("overlap", f"Day {day.day_number} has activities that overlap in time.")
                suggestions.append(Suggestion(target=AgentName.activities, constraints=Constraints(),
                                              reason=f"Re-schedule day {day.day_number} without overlaps."))
            for item in day.items:
                start = item.start_time
                end = item.end_minutes
                if start is None:
                    continue
                too_early = day.usable_from is not None and start < day.usable_from
                too_late = (day.usable_until is not None and end is not None
                            and end > day.usable_until.hour * 60 + day.usable_until.minute)
                if too_early or too_late:
                    conflict("outside_window",
                             f"Day {day.day_number}: '{item.name}' falls outside the usable hours "
                             f"(flight times).")
                    suggestions.append(Suggestion(target=AgentName.activities, constraints=Constraints(),
                                                  reason="Keep activities inside the usable hours."))
                    break
            outdoor = [i for i in day.items if i.category in {"nature"}]
            if outdoor and is_rainy(weather.get(day.date)):
                warnings.append(f"Day {day.day_number}: rain is expected but '{outdoor[0].name}' is outdoors.")
            if not day.items and day.usable_from is not None:
                warnings.append(f"Day {day.day_number} has no activities.")

        # 5. Soft warnings (do not block approval)
        if alloc is not None:
            for label, spent, share in (
                ("Flights", flight.total_price if flight else 0.0, alloc.flights),
                ("Accommodation", stay.total_price if stay else 0.0, alloc.stays),
                ("Food and transport", state.food_transport_estimate or 0.0, alloc.food_transport),
            ):
                if spent > share + 1e-9 and total <= req.budget:
                    warnings.append(f"{label} cost {money(spent, cur)}, above its planned share of "
                                    f"{money(share, cur)}, but the total is still within budget.")
        if flight and total > 0 and flight.total_price / req.budget > FLIGHT_HEAVY_SHARE:
            warnings.append(f"Flights use {flight.total_price / req.budget:.0%} of the whole budget.")
        remaining = round(req.budget - total, 2)
        if total and remaining / req.budget > UNDERSPEND_SHARE and not infeasible:
            warnings.append(f"{money(remaining, cur)} of the budget is unused - you could upgrade the "
                            f"stay or add activities.")
        if any(x.source.value != "live" for x in (flight, stay) if x is not None):
            warnings.append("Flight and hotel prices are estimates, not live fares. Check them before booking.")

        approved = not any(c.kind in BLOCKING for c in conflicts)
        return Review(approved=approved, conflicts=conflicts, suggestions=suggestions, warnings=warnings,
                      total_cost=total, budget=req.budget)

    # ---- check + readable verdict ---------------------------------------
    async def review(self, state: TripState, ctx: AgentContext) -> Review:
        result = self.check(state, ctx)
        facts = {
            "currency": state.request.currency, "budget": state.request.budget,
            "total_cost": result.total_cost, "approved": result.approved,
            "conflicts": [c.description for c in result.conflicts],
            "warnings": result.warnings[:6],
            "costs": {line.category: line.amount for line in state.cost_ledger()},
        }
        answer = await ask_llm(CRITIC_SYSTEM, facts, max_tokens=700)
        if answer:
            verdict = clean_text(answer.get("verdict"), 400)
            raw = answer.get("advice")
            advice = [t for t in (clean_text(a, 200) for a in raw) if t][:3] if isinstance(raw, list) else []
            if verdict:
                result.verdict, result.advice, result.used_llm = verdict, advice, True
        if not result.verdict:
            result.verdict = self._plain_verdict(result, state)
        return result

    @staticmethod
    def _plain_verdict(result: Review, state: TripState) -> str:
        cur = state.request.currency
        if result.approved:
            return (f"Plan fits the budget: {money(result.total_cost, cur)} of "
                    f"{money(result.budget, cur)}.")
        return f"{len(result.conflicts)} problem(s) found; see conflicts."
