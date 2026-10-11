"""Picks lunch and dinner suggestions for each day, near that day's sightseeing.

Pure code (no LLM): nearest well-documented restaurants first, restaurants that are confirmed
for the traveller's dietary needs (e.g. halal) get a strong bonus, nobody is suggested twice.
Meal costs are NOT added: food is already inside the "food + transport" budget estimate.
"""
from app.models.plan import DayPlan, MealSuggestion
from app.tools.restaurants import Restaurant, diet_keys, km_between

DIET_BONUS = 4.0
QUALITY_WEIGHT = 0.4


def _anchor(day: DayPlan, centre: tuple[float, float], last: bool = False) -> tuple[float, float]:
    pts = [(i.latitude, i.longitude) for i in day.items if i.latitude is not None and i.longitude is not None]
    if not pts:
        return centre
    if last:
        return pts[-1]
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _pick(pool: list[Restaurant], anchor: tuple[float, float], needs: list[str],
          used: set[str]) -> Restaurant | None:
    best, best_score = None, float("-inf")
    for r in pool:
        if r.name in used:
            continue
        score = QUALITY_WEIGHT * r.quality - km_between(anchor, (r.latitude, r.longitude))
        if needs and all(n in r.diets for n in needs):
            score += DIET_BONUS
        elif needs and any(n in r.diets for n in needs):
            score += DIET_BONUS / 2
        if score > best_score:
            best, best_score = r, score
    return best


def plan_meals(days: list[DayPlan], restaurants: list[Restaurant], centre: tuple[float, float],
               dietary_needs: list[str]) -> None:
    """Fills `day.meals` in place."""
    needs = diet_keys(dietary_needs)
    used: set[str] = set()
    for day in days:
        day.meals = []
        if day.usable_from is None or not restaurants:
            continue  # travel day / no data
        slots = []
        if day.usable_from.hour < 13:
            slots.append(("lunch", _anchor(day, centre)))
        if day.usable_until is None or day.usable_until.hour >= 17:
            slots.append(("dinner", _anchor(day, centre, last=True)))
        for slot, anchor in slots:
            r = _pick(restaurants, anchor, needs, used)
            if r is None:
                continue
            used.add(r.name)
            day.meals.append(MealSuggestion(
                slot=slot, name=r.name, cuisine=r.cuisine, latitude=r.latitude, longitude=r.longitude,
                area=f"{km_between(anchor, (r.latitude, r.longitude)):.1f} km from the day's sights",
                matches_diet=(all(n in r.diets for n in needs) if needs else None),
                website=r.website, source=r.source))
