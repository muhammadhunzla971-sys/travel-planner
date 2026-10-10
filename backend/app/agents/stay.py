"""Stay Agent: picks accommodation that fits its budget cap and the travel style."""
from app.agents.base import (
    AgentContext,
    BaseAgent,
    Constraints,
    Proposal,
    ask_llm,
    clean_text,
    money,
)
from app.agents.prompts import STAY_SYSTEM
from app.models.messages import AgentName
from app.models.request import TravelStyle


class StayAgent(BaseAgent):
    name = AgentName.stay

    async def propose(self, ctx: AgentContext, cap: float,
                      constraints: Constraints | None = None) -> Proposal:
        c = constraints or Constraints()
        stays = list(ctx.data.stays)
        currency = ctx.request.currency
        style = ctx.request.preferences.style
        if not stays:
            return Proposal(agent=self.name, summary="No accommodation found.", cost=0.0, cap=cap,
                            within_cap=True, considered=0,
                            reason="No accommodation options were available.")

        limit = min(cap, c.max_price) if c.max_price is not None else cap
        affordable = [s for s in stays if s.total_price <= limit]

        if not affordable:
            chosen = min(stays, key=lambda s: s.total_price)
            over = round(chosen.total_price - limit, 2)
            return Proposal(
                agent=self.name, summary=f"{chosen.name}: {money(chosen.total_price, currency)}",
                cost=chosen.total_price, cap=cap, within_cap=chosen.total_price <= cap,
                considered=len(stays), stay=chosen,
                reason=(f"Cheapest stay is {money(over, currency)} over the accommodation budget "
                        f"of {money(limit, currency)}."))

        # Shared hostel beds only for budget travellers (unless nothing else fits).
        pool = affordable
        if style != TravelStyle.budget:
            private = [s for s in affordable if s.kind != "hostel"]
            pool = private or affordable
        # budget -> cheapest; comfort/luxury -> best (most expensive) that still fits
        ranked = sorted(pool, key=lambda s: s.total_price, reverse=(style != TravelStyle.budget))
        chosen = ranked[0]
        reason = (f"Best {style.value}-style option within budget: {chosen.name} at "
                  f"{money(chosen.price_per_night, currency)}/night.")
        used_llm = False

        answer = await ask_llm(STAY_SYSTEM, {
            "trip": {"destination": ctx.request.destination, "travelers": ctx.request.travelers,
                     "nights": ctx.request.nights, "style": style.value},
            "candidates": [{
                "id": s.id, "name": s.name, "kind": s.kind, "price_per_night": s.price_per_night,
                "total_price": s.total_price, "currency": s.currency, "amenities": s.amenities,
            } for s in ranked[:3]],
        }, max_tokens=500) if len(ranked) > 1 else None
        if answer:
            picked = {s.id: s for s in ranked[:3]}.get(str(answer.get("choice")))
            text = clean_text(answer.get("reason"), 200)
            if picked and text:
                chosen, reason, used_llm = picked, text, True

        return Proposal(agent=self.name, summary=f"{chosen.name}: {money(chosen.total_price, currency)}",
                        cost=chosen.total_price, cap=cap, within_cap=chosen.total_price <= cap,
                        reason=reason, used_llm=used_llm, considered=len(stays), stay=chosen)
