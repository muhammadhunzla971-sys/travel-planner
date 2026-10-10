"""Flight Agent: picks the best flight that fits its budget cap."""
from app.agents.base import (
    AgentContext,
    BaseAgent,
    Constraints,
    Proposal,
    ask_llm,
    clean_text,
    money,
)
from app.agents.prompts import FLIGHT_SYSTEM
from app.models.messages import AgentName
from app.models.plan import FlightOption


def is_late_arrival(flight: FlightOption) -> bool:
    """Arrives (local time) between 23:00 and 06:00 - hard to get to the hotel."""
    hour = flight.arrive_at.hour
    return hour >= 23 or hour < 6


def _score(f: FlightOption, pool: list[FlightOption]) -> float:
    """Lower is better. Price matters most, then time in the air, then stops."""
    max_price = max(x.total_price for x in pool) or 1.0
    max_dur = max((x.duration_minutes or 0) for x in pool) or 1
    max_stops = max(x.stops for x in pool) or 1
    return (0.55 * f.total_price / max_price
            + 0.30 * (f.duration_minutes or 0) / max_dur
            + 0.15 * f.stops / max_stops
            + (0.25 if is_late_arrival(f) else 0.0))


def _describe(f: FlightOption) -> str:
    stops = "direct" if f.stops == 0 else f"{f.stops} stop{'s' if f.stops > 1 else ''}"
    dur = f", {f.duration_minutes // 60}h{f.duration_minutes % 60:02d}m" if f.duration_minutes else ""
    return f"{money(f.total_price, f.currency)} ({stops}{dur})"


class FlightAgent(BaseAgent):
    name = AgentName.flight

    async def propose(self, ctx: AgentContext, cap: float,
                      constraints: Constraints | None = None) -> Proposal:
        c = constraints or Constraints()
        flights = list(ctx.data.flights)
        currency = ctx.request.currency
        if not flights:
            return Proposal(agent=self.name, summary="No flights in this plan.", cost=0.0, cap=cap,
                            within_cap=True, considered=0,
                            reason="No origin was given or no flights were found, so flights are excluded.")

        notes: list[str] = []
        pool = flights
        max_stops = c.max_stops if c.max_stops is not None else ctx.request.preferences.max_stops
        if max_stops is not None:
            fewer = [f for f in pool if f.stops <= max_stops]
            if fewer:
                pool = fewer
            else:
                notes.append(f"no flight has {max_stops} stops or fewer")
        if c.avoid_late_arrival:
            daytime = [f for f in pool if not is_late_arrival(f)]
            if daytime:
                pool = daytime
            else:
                notes.append("every option arrives late at night")

        limit = min(cap, c.max_price) if c.max_price is not None else cap
        affordable = [f for f in pool if f.total_price <= limit]

        if not affordable:
            chosen = min(pool, key=lambda f: f.total_price)
            over = round(chosen.total_price - limit, 2)
            reason = (f"Cheapest option is {money(over, currency)} over the flight budget of "
                      f"{money(limit, currency)}.")
            used_llm = False
        else:
            ranked = sorted(affordable, key=lambda f: _score(f, affordable))
            chosen = ranked[0]
            reason = f"Best balance of price, duration and stops within budget: {_describe(chosen)}."
            used_llm = False
            answer = await ask_llm(FLIGHT_SYSTEM, {
                "trip": {"destination": ctx.request.destination, "travelers": ctx.request.travelers,
                         "style": ctx.request.preferences.style.value,
                         "max_stops_preference": max_stops},
                "candidates": [{
                    "id": f.id, "airline": f.airline, "price": f.total_price, "currency": f.currency,
                    "stops": f.stops, "duration_minutes": f.duration_minutes,
                    "arrives_local": f.arrive_at.strftime("%Y-%m-%d %H:%M"),
                } for f in ranked[:3]],
            }, max_tokens=500) if len(ranked) > 1 else None
            if answer:
                by_id = {f.id: f for f in ranked[:3]}
                picked = by_id.get(str(answer.get("choice")))
                text = clean_text(answer.get("reason"), 200)
                if picked and text:
                    chosen, reason, used_llm = picked, text, True

        if notes:
            reason += " Note: " + "; ".join(notes) + "."
        return Proposal(agent=self.name, summary=f"{chosen.airline}: {_describe(chosen)}",
                        cost=chosen.total_price, cap=cap, within_cap=chosen.total_price <= cap,
                        reason=reason, used_llm=used_llm, considered=len(flights), flight=chosen)
