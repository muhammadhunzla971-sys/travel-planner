"""Activities Agent: builds the day-by-day schedule.

The selection is rule-based (so it is predictable and always respects time windows and
budget); the LLM only adds a theme + tip per day, never changes which places are used.

Rules it follows:
  * usable hours per day come from the flights (arrival day starts ~2.5h after landing,
    departure day ends ~4h before take-off); without flights: 09:00-19:00
  * number of places per day depends on the pace (relaxed 2 / balanced 3 / packed 4)
  * rainy days prefer indoor places, dry days prefer outdoor ones
  * interests boost matching categories; nearby places are grouped on the same day
  * total entry fees never exceed the cap (when the cap is hit, only free places are added)
"""
import math
import re
from dataclasses import dataclass
from datetime import date, time, timedelta

from app.agents.base import (
    AgentContext,
    BaseAgent,
    Constraints,
    Proposal,
    ask_llm,
    clean_text,
    money,
)
from app.agents.prompts import ACTIVITIES_SYSTEM
from app.models.messages import AgentName
from app.models.plan import ActivityItem, DataSource, DayPlan
from app.models.request import Pace
from app.tools.geo import haversine_km
from app.tools.places import Place
from app.tools.weather import DayWeather

DEFAULT_START = 9 * 60       # 09:00
DEFAULT_END = 19 * 60        # 19:00
AFTER_LANDING = 150          # minutes between landing and being ready for sightseeing
BEFORE_TAKEOFF = 240         # minutes to leave for the airport before the flight
FIRST_DAY_START_NO_FLIGHT = 14 * 60
LAST_DAY_END_NO_FLIGHT = 11 * 60
TRAVEL_GAP = 30
MIN_WINDOW = 60

DURATION_MIN = {"museum": 120, "historic": 90, "religious": 45, "nature": 90,
                "landmark": 45, "sightseeing": 60, "food": 75}
PER_DAY = {Pace.relaxed: 2, Pace.balanced: 3, Pace.packed: 4}
INDOOR = {"museum", "religious", "food"}
OUTDOOR = {"nature", "landmark", "sightseeing", "historic"}

_INTEREST_RULES = [
    (("histor", "heritage", "ancient"), {"historic", "museum", "religious"}),
    (("museum", "art", "gallery"), {"museum"}),
    (("nature", "park", "outdoor", "hik", "garden"), {"nature"}),
    (("food", "eat", "cuisine", "restaurant"), {"food"}),
    (("relig", "spiritual", "mosque", "church", "temple"), {"religious"}),
    (("shop", "market", "bazaar"), {"landmark"}),
    (("culture", "cultural"), {"museum", "historic", "religious"}),
]


def interest_categories(interests: list[str]) -> set[str]:
    wanted: set[str] = set()
    for raw in interests:
        text = raw.lower()
        for keywords, categories in _INTEREST_RULES:
            if any(k in text for k in keywords):
                wanted |= categories
    return wanted


def is_rainy(w: DayWeather | None) -> bool:
    if w is None:
        return False
    text = (w.summary or "").lower()
    return (w.precipitation_mm or 0) >= 2.0 or any(k in text for k in ("rain", "snow", "thunder", "shower", "drizzle"))


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _to_time(minutes: int) -> time:
    minutes = max(0, min(minutes, 24 * 60 - 1))
    return time(minutes // 60, minutes % 60)


def day_windows(ctx: AgentContext) -> list[tuple[int, int] | None]:
    """Usable (start, end) minutes for every day of the trip, or None if the day is unusable."""
    flight = ctx.flight
    windows: list[tuple[int, int] | None] = []
    for i in range(ctx.request.num_days):
        d: date = ctx.request.start_date + timedelta(days=i)
        start, end = DEFAULT_START, DEFAULT_END
        if flight is None:
            if i == 0:
                start = FIRST_DAY_START_NO_FLIGHT
            if i == ctx.request.num_days - 1:
                end = LAST_DAY_END_NO_FLIGHT
        else:
            arrive = flight.arrive_at
            if arrive.date() > d:
                windows.append(None)  # still travelling
                continue
            if arrive.date() == d:
                start = max(start, _minutes(arrive.timetz()) + AFTER_LANDING)
            back = flight.return_depart_at
            if back is not None:
                if back.date() < d:
                    windows.append(None)
                    continue
                if back.date() == d:
                    end = min(end, _minutes(back.timetz()) - BEFORE_TAKEOFF)
        windows.append((start, end) if end - start >= MIN_WINDOW else None)
    return windows


@dataclass
class _Pick:
    place: Place
    cost: float


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "place"


def _base_score(p: Place, wanted: set[str]) -> float:
    return 2.0 * math.log10((p.popularity or 0) + 10) + (2.0 if p.category in wanted else 0.0)


def _distance(a: Place, b: Place) -> float:
    if None in (a.latitude, a.longitude, b.latitude, b.longitude):
        return 0.0
    return haversine_km(a.latitude, a.longitude, b.latitude, b.longitude)  # type: ignore[arg-type]


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?" else text + "."


def _weather_by_date(ctx: AgentContext) -> dict[date, DayWeather]:
    return {w.date: w for w in ctx.data.weather}


class ActivitiesAgent(BaseAgent):
    name = AgentName.activities

    async def propose(self, ctx: AgentContext, cap: float, constraints: Constraints | None = None,
                      narrate: bool = True) -> Proposal:
        c = constraints or Constraints()
        limit = min(cap, c.max_price) if c.max_price is not None else cap
        fx = ctx.data.fx.rate
        travelers = ctx.request.travelers
        currency = ctx.request.currency
        wanted = interest_categories(ctx.request.preferences.interests)
        per_day = PER_DAY[ctx.request.preferences.pace]
        weather = _weather_by_date(ctx)
        windows = day_windows(ctx)

        remaining = list(ctx.data.attractions)
        spent = 0.0
        skipped_paid = 0
        days: list[DayPlan] = []

        for i, window in enumerate(windows):
            d = ctx.request.start_date + timedelta(days=i)
            plan = DayPlan(day_number=i + 1, date=d)
            w = weather.get(d)
            rainy = is_rainy(w)
            if window is None:
                plan.notes = "Travel day - no sightseeing planned."
                days.append(plan)
                continue
            start, end = window
            plan.usable_from, plan.usable_until = _to_time(start), _to_time(end)
            t = start
            anchor: Place | None = None

            while len(plan.items) < per_day and remaining:
                options: list[_Pick] = []
                for p in remaining:
                    duration = DURATION_MIN.get(p.category, 60)
                    if t + duration > end:
                        continue
                    cost = round(p.est_entry_usd * fx * travelers, 2)
                    if c.free_only and cost > 0:
                        continue
                    if spent + cost > limit + 1e-9:
                        skipped_paid += 1
                        continue
                    options.append(_Pick(p, cost))
                if not options:
                    break

                def score(pick: _Pick, rainy: bool = rainy, anchor: Place | None = anchor,
                          plan: DayPlan = plan) -> float:
                    p = pick.place
                    s = _base_score(p, wanted)
                    if rainy:
                        s += 1.5 if p.category in INDOOR else -1.0 if p.category == "nature" else 0.0
                    else:
                        s += 1.0 if p.category in OUTDOOR else 0.0
                    if anchor is not None:
                        s -= 0.25 * _distance(anchor, p)
                    s -= 1.2 * sum(1 for it in plan.items if it.category == p.category)  # variety
                    return s

                best = max(options, key=score)
                p, cost = best.place, best.cost
                duration = DURATION_MIN.get(p.category, 60)
                fee_note = "Entry fee is an estimate." if cost > 0 else None
                plan.items.append(ActivityItem(
                    id=f"act-{_slug(p.name)}", name=p.name, category=p.category,
                    start_time=_to_time(t), duration_minutes=duration, cost=cost,
                    area=f"{p.distance_km} km from centre" if p.distance_km is not None else None,
                    notes=fee_note,
                    source=DataSource.estimated if cost > 0 else p.source))
                spent += cost
                remaining.remove(p)
                anchor = p
                t += duration + TRAVEL_GAP
                if 750 <= t < 810:  # lunch break 12:30-13:30
                    t = 810

            if rainy:
                if w is not None and w.source == DataSource.estimated:
                    plan.notes = "Rain is likely (typical weather for these dates) - indoor places are prioritised."
                else:
                    plan.notes = "Rain expected - indoor places are prioritised."
            if not plan.items:
                plan.notes = (plan.notes + " " if plan.notes else "") + "Free day - nothing fitted the time or budget."
            days.append(plan)

        total = round(sum(d.cost() for d in days), 2)
        count = sum(len(d.items) for d in days)
        reason = f"{count} places scheduled over {len(days)} days, {money(total, currency)} of entry fees."
        if skipped_paid:
            reason += " Some paid places were left out to stay within the activities budget."

        used_llm = False
        if narrate and count:
            used_llm = await self.narrate(ctx, days)
        return Proposal(agent=self.name, summary=f"{count} activities, {money(total, currency)}",
                        cost=total, cap=cap, within_cap=total <= cap, reason=reason,
                        used_llm=used_llm, considered=len(ctx.data.attractions), days=days)

    async def narrate(self, ctx: AgentContext, days: list[DayPlan]) -> bool:
        """Ask the LLM for a theme + tip per day. Ignores anything unusable."""
        weather = _weather_by_date(ctx)
        answer = await ask_llm(ACTIVITIES_SYSTEM, {
            "trip": {"destination": ctx.request.destination, "style": ctx.request.preferences.style.value,
                     "interests": ctx.request.preferences.interests},
            "days": [{
                "day": d.day_number, "date": d.date.isoformat(),
                "weather": (weather[d.date].summary if d.date in weather else None),
                "places": [{"name": i.name, "category": i.category} for i in d.items],
            } for d in days if d.items],
        }, max_tokens=900)
        rows = answer.get("days") if answer else None
        if not isinstance(rows, list):
            return False
        by_day = {d.day_number: d for d in days}
        used = False
        for row in rows:
            if not isinstance(row, dict):
                continue
            day = by_day.get(row.get("day")) if isinstance(row.get("day"), int) else None
            theme, tip = clean_text(row.get("theme"), 60), clean_text(row.get("tip"), 160)
            if day is None or not day.items or not (theme or tip):
                continue
            parts = [p for p in (_sentence(theme), _sentence(tip), day.notes or "") if p]
            day.notes = " ".join(parts)
            used = True
        return used


__all__ = ["ActivitiesAgent", "day_windows", "interest_categories", "is_rainy"]

