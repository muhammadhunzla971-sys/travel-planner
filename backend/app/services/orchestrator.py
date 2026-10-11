"""The orchestrator: runs research, lets the agents propose, asks the critic to review and
negotiates (up to `max_iterations` rounds) until the plan fits the budget and the checks pass.

Negotiation rules (all deterministic code; the LLM never decides whether a plan is valid):
  * critic says "late arrival"  -> flight agent must avoid night arrivals
  * critic says "over budget"   -> money is squeezed out of the most flexible agents first
                                   (activities > stay > flight), never below what is possible
  * a night flight is accepted (waived, shown as a warning) only if a daytime one cannot fit
  * an impossible budget is reported straight away instead of looping
  * stops when approved, when no more changes are possible, or when rounds/time run out
"""
import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from app.agents import (
    ActivitiesAgent,
    AgentContext,
    Constraints,
    CriticAgent,
    FlightAgent,
    Proposal,
    Review,
    StayAgent,
)
from app.agents.base import ask_llm, clean_text, money
from app.agents.flight import flight_floor, is_late_arrival
from app.agents.prompts import SUMMARY_SYSTEM
from app.models.messages import AgentMessage, AgentName, MessageType, make_message
from app.models.request import TripRequest
from app.models.state import TripState, TripStatus
from app.services.meals import plan_meals
from app.services.negotiation import BudgetBreakdown, build_breakdown, squeeze_targets
from app.services.trip_data import TripData, gather_trip_data

log = logging.getLogger(__name__)

NEGOTIABLE = (AgentName.flight, AgentName.stay, AgentName.activities)


class TimelineEvent(BaseModel):
    seq: int
    round: int
    stage: str  # research | propose | review | negotiate | final
    from_agent: str
    to_agent: str
    type: str
    text: str


class PlanSummary(BaseModel):
    headline: str = ""
    overview: str = ""
    tips: list[str] = Field(default_factory=list)
    used_llm: bool = False


class PlanResult(BaseModel):
    trip: TripState
    summary: PlanSummary
    review: Review
    breakdown: BudgetBreakdown
    rounds: int
    timeline: list[TimelineEvent]
    data_sources: dict[str, str]
    data_warnings: list[str]
    center: tuple[float, float] | None = None  # destination centre, for the map


EventCallback = Callable[[TimelineEvent], Awaitable[None] | None]


def _label(agent: AgentName | str) -> str:
    name = agent.value if isinstance(agent, AgentName) else agent
    return name.capitalize()


class Orchestrator:
    def __init__(self, on_event: EventCallback | None = None, time_budget_s: float = 45.0) -> None:
        self.on_event = on_event
        self.time_budget_s = time_budget_s
        self.timeline: list[TimelineEvent] = []
        self._started = time.monotonic()
        self.flight_agent = FlightAgent()
        self.stay_agent = StayAgent()
        self.activities_agent = ActivitiesAgent()
        self.critic = CriticAgent()

    # ---- events ----------------------------------------------------------
    async def _emit(self, rnd: int, stage: str, from_agent: str, to_agent: str, type_: str, text: str) -> None:
        event = TimelineEvent(seq=len(self.timeline) + 1, round=rnd, stage=stage, from_agent=from_agent,
                              to_agent=to_agent, type=type_, text=text)
        self.timeline.append(event)
        if self.on_event is not None:
            try:
                result: Any = self.on_event(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # a broken listener must never break planning
                log.exception("event callback failed")

    def _out_of_time(self) -> bool:
        return time.monotonic() - self._started > self.time_budget_s

    # ---- main entry ------------------------------------------------------
    async def plan(self, request: TripRequest, data: TripData | None = None) -> PlanResult:
        self._started = time.monotonic()
        self.timeline = []
        await self._emit(0, "research", "orchestrator", "orchestrator", "request",
                         f"Researching {request.destination}: places, weather, exchange rate, flights, stays.")
        data = data or await gather_trip_data(request)
        live = sorted(k for k, v in data.sources.items() if v == "live")
        await self._emit(0, "research", "orchestrator", "orchestrator", "approval",
                         f"Research done. Live data: {', '.join(live) or 'none'}. "
                         f"Everything else is clearly marked as estimated.")

        alloc = data.allocation
        state = TripState(request=request, allocation=alloc, status=TripStatus.planning,
                          flight_options=data.flights, stay_options=data.stays,
                          food_transport_estimate=data.food_transport_estimate)
        ctx = AgentContext(request=request, data=data)
        constraints = {a: Constraints() for a in NEGOTIABLE}
        caps = {AgentName.flight: alloc.flights, AgentName.stay: alloc.stays,
                AgentName.activities: alloc.activities}
        waived: set[str] = set()
        notes: list[str] = []
        proposals: dict[AgentName, Proposal] = {}

        # Round 0: everybody proposes within their share of the budget.
        await self._run_agents(state, ctx, caps, constraints, proposals, set(NEGOTIABLE))
        review = self.critic.check(state, ctx, waived)
        await self._emit_review(state.iteration, review, state)

        # Negotiation rounds.
        while not review.approved and state.can_negotiate():
            if self._out_of_time():
                notes.append("Planning time ran out before every issue was resolved.")
                break
            rnd = state.next_round()
            rerun = await self._decide(state, ctx, review, constraints, caps, waived, proposals, notes, rnd)
            if not rerun:
                break  # nothing left to change
            await self._run_agents(state, ctx, caps, constraints, proposals, rerun)
            review = self.critic.check(state, ctx, waived)
            await self._emit_review(rnd, review, state)

        return await self._finish(state, ctx, review, waived, notes, data)

    # ---- running agents --------------------------------------------------
    async def _run_agents(self, state: TripState, ctx: AgentContext, caps: dict[AgentName, float],
                          constraints: dict[AgentName, Constraints], proposals: dict[AgentName, Proposal],
                          rerun: set[AgentName]) -> None:
        rnd = state.iteration
        type_ = MessageType.proposal if rnd == 0 else MessageType.counter_proposal
        previous_flight_id = state.selected_flight.id if state.selected_flight else None

        tasks: dict[AgentName, Awaitable[Proposal]] = {}
        if AgentName.flight in rerun:
            tasks[AgentName.flight] = self.flight_agent.propose(
                ctx, caps[AgentName.flight], constraints[AgentName.flight])
        if AgentName.stay in rerun:
            tasks[AgentName.stay] = self.stay_agent.propose(
                ctx, caps[AgentName.stay], constraints[AgentName.stay])
        results = dict(zip(tasks, await asyncio.gather(*tasks.values()), strict=True))

        if AgentName.flight in results:
            proposals[AgentName.flight] = results[AgentName.flight]
            state.selected_flight = results[AgentName.flight].flight
            ctx.flight = state.selected_flight
        if AgentName.stay in results:
            proposals[AgentName.stay] = results[AgentName.stay]
            state.selected_stay = results[AgentName.stay].stay

        flight_changed = (state.selected_flight.id if state.selected_flight else None) != previous_flight_id
        if AgentName.activities in rerun or flight_changed or rnd == 0:
            act = await self.activities_agent.propose(
                ctx, caps[AgentName.activities], constraints[AgentName.activities], narrate=False)
            proposals[AgentName.activities] = act
            state.days = act.days
            results[AgentName.activities] = act

        for agent in NEGOTIABLE:
            p = results.get(agent)
            if p is None:
                continue
            state.post(p.to_message(type=type_))
            verb = "proposes" if rnd == 0 else "counter-proposes"
            fit = "within its share" if p.within_cap else f"over its share ({money(p.cap, ctx.request.currency)})"
            await self._emit(rnd, "propose" if rnd == 0 else "negotiate", agent.value, "orchestrator",
                             type_.value, f"{_label(agent)} {verb}: {p.summary} - {fit}. {p.reason}")

    async def _emit_review(self, rnd: int, review: Review, state: TripState) -> None:
        if review.approved:
            text = f"Critic approves. Total {money(review.total_cost, state.request.currency)} of {money(review.budget, state.request.currency)}."
            if review.conflicts:
                text += " Open issues: " + "; ".join(c.description for c in review.conflicts)
            type_ = MessageType.approval
        else:
            text = "Critic objects: " + " ".join(c.description for c in review.conflicts)
            type_ = MessageType.constraint
        state.post(make_message(AgentName.critic, AgentName.orchestrator, type_, payload={
            "approved": review.approved, "conflicts": [c.kind for c in review.conflicts],
            "total_cost": review.total_cost}, reason=text))
        await self._emit(rnd, "review", "critic", "orchestrator", type_.value, text)

    # ---- deciding what to change ----------------------------------------
    async def _decide(self, state: TripState, ctx: AgentContext, review: Review,
                      constraints: dict[AgentName, Constraints], caps: dict[AgentName, float],
                      waived: set[str], proposals: dict[AgentName, Proposal], notes: list[str],
                      rnd: int) -> set[AgentName]:
        """Turn the critic's findings into constraints. Returns which agents must re-propose."""
        cur = state.request.currency
        kinds = {c.kind for c in review.conflicts}
        rerun: set[AgentName] = set()
        flight_c = constraints[AgentName.flight]

        async def tell(agent: AgentName, text: str) -> None:
            state.post(make_message(AgentName.orchestrator, agent, MessageType.constraint,
                                    payload=constraints[agent].model_dump(mode="json"), reason=text))
            await self._emit(rnd, "negotiate", "orchestrator", agent.value, "constraint", text)

        if "late_arrival" in kinds and not flight_c.avoid_late_arrival:
            flight_c.avoid_late_arrival = True
            rerun.add(AgentName.flight)
            await tell(AgentName.flight, "Choose a flight that lands during the day.")

        if "over_budget" in kinds:
            def plan_cuts() -> tuple[dict[AgentName, float], dict[AgentName, float], float, float]:
                """Costs after any pending flight switch, and what must be cut from each agent."""
                costs = {a: proposals[a].cost for a in NEGOTIABLE if a in proposals}
                floors = {AgentName.flight: flight_floor(ctx, flight_c),
                          AgentName.stay: min((s.total_price for s in ctx.data.stays), default=0.0),
                          AgentName.activities: 0.0}
                overage = state.total_cost() - state.request.budget
                if AgentName.flight in costs and floors[AgentName.flight] > costs[AgentName.flight]:
                    # switching to a daytime flight will cost more: count that up front
                    bump = floors[AgentName.flight] - costs[AgentName.flight]
                    costs[AgentName.flight] += bump
                    overage += bump
                targets, unmet = squeeze_targets(costs, floors, overage + 0.01)
                return costs, targets, overage, unmet

            costs, targets, overage, unmet = plan_cuts()
            if unmet > 0 and flight_c.avoid_late_arrival:
                # A daytime flight is too expensive for this budget: accept the night flight.
                flight_c.avoid_late_arrival = False
                waived.add("late_arrival")
                rerun.add(AgentName.flight)
                notes.append("A night-time arrival was accepted because a daytime flight does not fit the budget.")
                await self._emit(rnd, "negotiate", "orchestrator", "flight", "constraint",
                                 "A daytime flight does not fit the budget; accepting a late arrival as a trade-off.")
                costs, targets, overage, unmet = plan_cuts()

            for agent, target in targets.items():
                if target < costs[agent] - 0.005:
                    constraints[agent].max_price = target
                    rerun.add(agent)
                    await tell(agent, f"Over budget by {money(max(overage, 0), cur)}: please come down from "
                                      f"{money(costs[agent], cur)} to at most {money(target, cur)}.")
            if unmet > 0:
                notes.append(f"Could not cut the last {money(unmet, cur)} to fit the budget.")

        if kinds & {"overlap", "outside_window"}:
            rerun.add(AgentName.activities)
            await tell(AgentName.activities, "Re-plan the days so activities do not overlap and stay inside the usable hours.")

        if AgentName.flight in rerun:
            old = state.selected_flight
            if old is not None and is_late_arrival(old) and flight_c.avoid_late_arrival:
                notes.append("Switched to a flight that lands in daytime instead of a night arrival.")
        return rerun

    # ---- finishing -------------------------------------------------------
    async def _finish(self, state: TripState, ctx: AgentContext, review: Review, waived: set[str],
                      notes: list[str], data: TripData) -> PlanResult:
        has_activities = any(d.items for d in state.days)
        narrate_task = (self.activities_agent.narrate(ctx, state.days) if has_activities
                        else asyncio.sleep(0, result=False))
        _narrated, final_review, summary = await asyncio.gather(
            narrate_task, self.critic.review(state, ctx, waived), self._summarize(state, ctx, notes))

        centre = (data.destination.latitude, data.destination.longitude)
        needs = state.request.preferences.dietary_needs
        plan_meals(state.days, data.restaurants, centre, needs)
        meals = [m for d in state.days for m in d.meals]
        if needs and meals and not any(m.matches_diet for m in meals):
            notes.append(f"None of the suggested restaurants is confirmed for your dietary needs ({', '.join(needs)}) "
                         "in OpenStreetMap, which does not tag every place. Please check with the restaurant.")

        state.conflicts = final_review.conflicts
        extra = []
        if not final_review.approved:
            extra.append("Could not resolve every issue within the allowed negotiation rounds: "
                         + "; ".join(c.description for c in final_review.conflicts))
        state.warnings = list(dict.fromkeys(data.warnings + notes + extra + final_review.warnings))
        state.status = (TripStatus.completed if final_review.approved and not final_review.conflicts
                        else TripStatus.completed_with_warnings)
        state.post(make_message(AgentName.orchestrator, AgentName.orchestrator, MessageType.approval,
                                payload={"status": state.status.value, "rounds": state.iteration},
                                reason=final_review.verdict))
        await self._emit(state.iteration, "final", "orchestrator", "orchestrator", "approval",
                         f"Plan ready ({state.status.value}) after {state.iteration} negotiation round(s). "
                         f"{final_review.verdict}")
        return PlanResult(trip=state, summary=summary, review=final_review, breakdown=build_breakdown(state),
                          rounds=state.iteration, timeline=self.timeline, data_sources=data.sources,
                          data_warnings=data.warnings, center=centre)

    async def _summarize(self, state: TripState, ctx: AgentContext, notes: list[str]) -> PlanSummary:
        req = state.request
        flight, stay = state.selected_flight, state.selected_stay
        places = [i.name for d in state.days for i in d.items]
        cost = state.total_cost()
        estimated = any(x.source.value != "live" for x in (flight, stay) if x is not None)
        facts = {
            "destination": req.destination, "start": req.start_date.isoformat(), "end": req.end_date.isoformat(),
            "nights": req.nights, "travelers": req.travelers, "currency": req.currency,
            "budget": req.budget, "total_cost": cost,
            "flight": f"{flight.airline}, {flight.stops} stop(s), {flight.total_price} {flight.currency}" if flight else None,
            "stay": f"{stay.name}, {stay.total_price} {stay.currency}" if stay else None,
            "places": places[:8], "trade_offs": notes, "prices_are_estimates": estimated,
        }
        answer = await ask_llm(SUMMARY_SYSTEM, facts, max_tokens=700)
        if answer:
            headline, overview = clean_text(answer.get("headline"), 120), clean_text(answer.get("overview"), 600)
            raw = answer.get("tips")
            tips = [t for t in (clean_text(x, 160) for x in raw) if t][:3] if isinstance(raw, list) else []
            if headline and overview:
                return PlanSummary(headline=headline, overview=overview, tips=tips, used_llm=True)
        parts = []
        if flight:
            parts.append(f"Flights: {money(flight.total_price, req.currency)}")
        if stay:
            parts.append(f"stay: {money(stay.total_price, req.currency)}")
        parts.append(f"{len(places)} activities")
        overview = (f"{', '.join(parts)}. Total {money(cost, req.currency)} of your "
                    f"{money(req.budget, req.currency)} budget."
                    + (" Flight and hotel prices are estimates." if estimated else ""))
        return PlanSummary(headline=f"{req.nights} nights in {req.destination}", overview=overview)


async def plan_trip(request: TripRequest, data: TripData | None = None,
                    on_event: EventCallback | None = None) -> PlanResult:
    return await Orchestrator(on_event=on_event).plan(request, data)


__all__ = ["AgentMessage", "Orchestrator", "PlanResult", "PlanSummary", "TimelineEvent", "plan_trip"]
