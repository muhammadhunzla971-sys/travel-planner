from datetime import date, time

from app.models.plan import ActivityItem, DayPlan
from app.services.meals import plan_meals
from app.tools.restaurants import (
    Restaurant,
    diet_keys,
    find_restaurants,
    parse_overpass,
)
from tests.fakes import ISTANBUL, patch_all

OVERPASS = {"elements": [
    {"type": "node", "lat": 41.0086, "lon": 28.9802, "tags": {
        "name": "Sultanahmet Koftecisi", "amenity": "restaurant", "cuisine": "turkish;kebab",
        "website": "https://example.com", "opening_hours": "Mo-Su 10:00-22:00", "diet:halal": "yes"}},
    {"type": "way", "center": {"lat": 41.0256, "lon": 28.9744}, "tags": {
        "name": "Galata Veg", "cuisine": "vegetarian", "diet:vegetarian": "only"}},
    {"type": "node", "lat": 41.0100, "lon": 28.9500, "tags": {"name": "Plain Diner"}},
    {"type": "node", "lat": 41.0100, "lon": 28.9500, "tags": {"name": "plain diner"}},   # duplicate name
    {"type": "node", "lat": 41.0, "lon": 28.9, "tags": {"cuisine": "x"}},                  # no name
    {"type": "node", "tags": {"name": "No Coordinates"}},
]}


def test_parse_overpass_filters_ranks_and_reads_diet_tags():
    rs = parse_overpass(ISTANBUL, OVERPASS)
    assert rs[0].name == "Sultanahmet Koftecisi"          # best documented first
    assert {r.name for r in rs} == {"Sultanahmet Koftecisi", "Galata Veg", "Plain Diner"}
    by = {r.name: r for r in rs}
    assert by["Sultanahmet Koftecisi"].diets == ["halal"] and by["Sultanahmet Koftecisi"].cuisine == "turkish, kebab"
    assert by["Galata Veg"].diets == ["vegetarian"]                      # way: uses "center"
    assert by["Plain Diner"].diets == [] and by["Plain Diner"].distance_km is not None


def test_diet_keys_understands_free_text():
    assert diet_keys(["Halal food", "gluten-free", "no nuts"]) == ["halal", "gluten"]
    assert diet_keys([]) == []


async def test_find_restaurants_live_and_cached(monkeypatch):
    calls = []
    patch_all(monkeypatch, {"overpass": OVERPASS}, calls)
    first = await find_restaurants(ISTANBUL)
    second = await find_restaurants(ISTANBUL)
    assert len(first) == 3 and first == second and len(calls) == 2  # two mirrors asked once, 2nd call cached
    assert "around:" in calls[0][1]["data"] and "restaurant" in calls[0][1]["data"]


def _day(n, items, usable_from=time(9, 0), usable_until=time(19, 0)):
    return DayPlan(day_number=n, date=date(2030, 1, n), items=items, usable_from=usable_from,
                   usable_until=usable_until)


def _item(name, lat, lon):
    return ActivityItem(id=name, name=name, start_time=time(9, 0), latitude=lat, longitude=lon)


R_NEAR = Restaurant(name="Near", latitude=41.0090, longitude=28.9800, quality=1.0, diets=[])
R_HALAL = Restaurant(name="Halal Far", latitude=41.0200, longitude=28.9800, quality=1.0, diets=["halal"])
R_OTHER = Restaurant(name="Other", latitude=41.0095, longitude=28.9805, quality=2.0)


def test_meals_are_near_the_days_sights_and_never_repeated():
    days = [_day(1, [_item("A", 41.0086, 28.9802)]), _day(2, [_item("B", 41.0086, 28.9802)]),
            _day(3, [], usable_from=None, usable_until=None)]
    plan_meals(days, [R_NEAR, R_OTHER, R_HALAL, Restaurant(name="Fourth", latitude=41.011, longitude=28.98)],
               (41.01, 28.95), [])
    names = [m.name for d in days for m in d.meals]
    assert [m.slot for m in days[0].meals] == ["lunch", "dinner"] and len(names) == len(set(names)) == 4
    assert days[2].meals == []                     # travel day
    assert all(m.matches_diet is None for d in days for m in d.meals)


def test_dietary_need_beats_distance():
    days = [_day(1, [_item("A", 41.0086, 28.9802)])]
    plan_meals(days, [R_NEAR, R_HALAL], (41.01, 28.95), ["Halal"])
    assert days[0].meals[0].name == "Halal Far" and days[0].meals[0].matches_diet is True
    assert days[0].meals[1].matches_diet is False   # only a non-halal place left: honestly flagged


def test_arrival_afternoon_gets_dinner_only_and_no_data_means_no_meals():
    late = _day(1, [], usable_from=time(15, 48))
    plan_meals([late], [R_NEAR], (41.01, 28.95), [])
    assert [m.slot for m in late.meals] == ["dinner"]
    empty = _day(1, [])
    plan_meals([empty], [], (41.01, 28.95), [])
    assert empty.meals == []


async def test_orchestrator_adds_meals_coordinates_and_map_centre():
    from app.models.request import TripPreferences
    from app.services.orchestrator import Orchestrator
    from tests.agent_helpers import make_ctx

    ctx = await make_ctx(budget=20_000, start_date=date(2031, 4, 21), end_date=date(2031, 4, 26),
                         preferences=TripPreferences(dietary_needs=["halal"]))
    ctx.data.restaurants = [R_NEAR, R_HALAL, R_OTHER, Restaurant(name="More", latitude=41.011, longitude=28.98),
                            Restaurant(name="Even More", latitude=41.012, longitude=28.981),
                            Restaurant(name="Lots", latitude=41.013, longitude=28.982),
                            Restaurant(name="Plenty", latitude=41.014, longitude=28.983),
                            Restaurant(name="Enough", latitude=41.015, longitude=28.984)]
    result = await Orchestrator().plan(ctx.request, ctx.data)
    assert result.center == (ISTANBUL.latitude, ISTANBUL.longitude)
    assert any(i.latitude is not None for d in result.trip.days for i in d.items)
    meals = [m for d in result.trip.days for m in d.meals]
    assert meals and meals[0].name == "Halal Far" and meals[0].matches_diet is True
    dumped = result.model_dump(mode="json")
    assert dumped["trip"]["days"][0]["meals"] is not None and dumped["center"] == [ISTANBUL.latitude, ISTANBUL.longitude]


def test_build_query_adds_diet_filters_only_when_asked():
    from app.tools.restaurants import build_query
    plain = build_query(ISTANBUL)
    assert '"amenity"="restaurant"' in plain and "diet:" not in plain
    halal = build_query(ISTANBUL, ["halal"])
    assert halal.count("around:") == 2 and "diet:halal" in halal and "out center" in halal


async def test_find_restaurants_sends_diet_filter(monkeypatch):
    calls: list = []
    patch_all(monkeypatch, {"overpass": OVERPASS}, calls)
    await find_restaurants(ISTANBUL, ["halal"])
    assert all("diet:halal" in c[1]["data"] for c in calls)


async def test_orchestrator_warns_when_no_meal_matches_diet():
    from app.models.request import TripPreferences
    from app.services.orchestrator import Orchestrator
    from tests.agent_helpers import make_ctx

    ctx = await make_ctx(budget=20_000, start_date=date(2031, 4, 21), end_date=date(2031, 4, 26),
                         preferences=TripPreferences(dietary_needs=["halal"]))
    ctx.data.restaurants = [Restaurant(name=f"Plain {i}", latitude=41.01 + i / 1000, longitude=28.98)
                            for i in range(8)]
    result = await Orchestrator().plan(ctx.request, ctx.data)
    assert any("dietary needs" in w and "Please check" in w for w in result.trip.warnings)


async def test_restaurants_fall_back_to_mirror_and_to_plain_query(monkeypatch):
    from app.tools.http import ProviderError
    calls: list = []

    async def fake(url, params=None, **kw):
        calls.append((url, params["data"]))
        if "kumi" not in url or "diet:halal" in params["data"]:
            raise ProviderError("busy")
        return OVERPASS

    monkeypatch.setattr("app.tools.restaurants.fetch_json", fake)
    rs = await find_restaurants(ISTANBUL, ["halal"])
    assert {r.name for r in rs} >= {"Plain Diner"}
    assert any("diet:halal" in q for _, q in calls) and any("diet:" not in q for _, q in calls)
