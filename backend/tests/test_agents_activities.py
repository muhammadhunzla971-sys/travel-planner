from datetime import time, timedelta

from app.agents import ActivitiesAgent, Constraints
from app.agents.activities import day_windows, interest_categories, is_rainy
from app.models.request import Pace, TripPreferences
from app.tools.weather import DayWeather
from tests.agent_helpers import default_places, fake_llm, make_ctx, place
from tests.fakes import USD_TO_PKR

BIG = 100_000.0


def rain_on(ctx, day_index: int) -> list[DayWeather]:
    d = ctx.request.start_date + timedelta(days=day_index)
    return [DayWeather(date=d, temp_min_c=5, temp_max_c=10, precipitation_mm=6.0, summary="rain")]


def minutes(t: time) -> int:
    return t.hour * 60 + t.minute


# ---- windows --------------------------------------------------------------
async def test_windows_without_flight_use_defaults():
    ctx = await make_ctx()
    w = day_windows(ctx)
    assert len(w) == ctx.request.num_days
    assert w[0] == (14 * 60, 19 * 60) and w[-1] == (9 * 60, 11 * 60) and w[1] == (9 * 60, 19 * 60)


async def test_windows_follow_flight_times():
    ctx = await make_ctx()
    ctx.flight = next(f for f in ctx.data.flights if f.id == "est-direct")  # lands 13:03, leaves 09:30
    w = day_windows(ctx)
    assert w[0][0] == 13 * 60 + 3 + 150          # 2.5h after landing
    assert w[-1] is None or w[-1][1] <= 9 * 60 + 30 - 240 + 1  # no time before a morning departure


async def test_windows_next_day_arrival_makes_first_day_a_travel_day():
    ctx = await make_ctx()
    ctx.flight = next(f for f in ctx.data.flights if f.id == "est-budget-late")  # lands 04:13 next day
    w = day_windows(ctx)
    assert w[0] is None and w[1] == (9 * 60, 19 * 60)
    assert w[-1] == (9 * 60, 20 * 60 + 40 - 240)  # leaves 20:40 -> must go at 16:40


# ---- interests / weather helpers -----------------------------------------
def test_interest_and_rain_helpers():
    assert interest_categories(["History", "street food"]) >= {"historic", "museum", "food"}
    assert interest_categories(["???"]) == set()
    assert is_rainy(DayWeather(date="2030-01-01", temp_min_c=1, temp_max_c=2, summary="rain"))
    assert is_rainy(DayWeather(date="2030-01-01", temp_min_c=1, temp_max_c=2, precipitation_mm=5, summary="x"))
    assert not is_rainy(DayWeather(date="2030-01-01", temp_min_c=1, temp_max_c=2, summary="clear sky"))
    assert not is_rainy(None)


# ---- planning -------------------------------------------------------------
async def test_plan_is_valid_and_respects_pace_windows_and_uniqueness():
    ctx = await make_ctx(preferences=TripPreferences(pace=Pace.relaxed))
    p = await ActivitiesAgent().propose(ctx, BIG)
    assert len(p.days) == ctx.request.num_days
    names = [i.name for d in p.days for i in d.items]
    assert len(names) == len(set(names)) and names
    for d in p.days:
        assert len(d.items) <= 2
        assert not d.has_overlaps()
        for item in d.items:
            assert minutes(item.start_time) >= minutes(d.usable_from)
            assert item.end_minutes <= minutes(d.usable_until)


async def test_packed_pace_schedules_more_than_relaxed():
    relaxed = await ActivitiesAgent().propose(
        await make_ctx(preferences=TripPreferences(pace=Pace.relaxed)), BIG)
    packed = await ActivitiesAgent().propose(
        await make_ctx(preferences=TripPreferences(pace=Pace.packed), attractions=default_places() * 1), BIG)
    count = lambda p: sum(len(d.items) for d in p.days)
    assert count(packed) > count(relaxed) or count(packed) == len(default_places())


async def test_rainy_day_prefers_indoor_and_dry_day_prefers_outdoor():
    places = [place("Indoor Museum", "museum", 5000), place("Outdoor Park", "nature", 5000)]
    ctx = await make_ctx(attractions=places, preferences=TripPreferences(pace=Pace.relaxed))
    ctx.data.weather = rain_on(ctx, 0)
    wet = await ActivitiesAgent().propose(ctx, BIG)
    assert wet.days[0].items[0].name == "Indoor Museum"
    assert "Rain expected" in wet.days[0].notes

    ctx2 = await make_ctx(attractions=places, preferences=TripPreferences(pace=Pace.relaxed))
    dry = await ActivitiesAgent().propose(ctx2, BIG)
    assert dry.days[0].items[0].name == "Outdoor Park"


async def test_interests_boost_matching_places():
    places = [place("Big Park", "nature", 20000), place("Small Museum", "museum", 12000)]
    ctx = await make_ctx(attractions=places,
                         preferences=TripPreferences(pace=Pace.relaxed, interests=["museums"]))
    p = await ActivitiesAgent().propose(ctx, BIG)
    assert p.days[0].items[0].name == "Small Museum"


async def test_budget_cap_is_never_exceeded():
    places = [place("Paid A", "museum", 9000, fee=20), place("Paid B", "museum", 8000, fee=20),
              place("Free Walk", "landmark", 100)]
    ctx = await make_ctx(attractions=places, travelers=1)
    p = await ActivitiesAgent().propose(ctx, 25.0)
    assert p.cost <= 25.0 and p.within_cap
    names = [i.name for d in p.days for i in d.items]
    assert "Free Walk" in names and sum(n.startswith("Paid") for n in names) == 1
    assert "left out" in p.reason


async def test_free_only_constraint():
    ctx = await make_ctx()
    p = await ActivitiesAgent().propose(ctx, BIG, Constraints(free_only=True))
    assert p.cost == 0 and any(d.items for d in p.days)


async def test_costs_scale_with_travelers_and_currency():
    ctx = await make_ctx(attractions=[place("Museum", "museum", 9000, fee=10)], fx=USD_TO_PKR,
                         currency="PKR", travelers=2, preferences=TripPreferences(pace=Pace.relaxed))
    p = await ActivitiesAgent().propose(ctx, 10_000_000)
    item = next(i for d in p.days for i in d.items)
    assert item.cost == 10 * 280 * 2 and "estimate" in item.notes
    assert item.source.value == "estimated"  # fee is estimated even if the place is live


async def test_travel_day_and_empty_places():
    ctx = await make_ctx()
    ctx.flight = next(f for f in ctx.data.flights if f.id == "est-budget-late")
    p = await ActivitiesAgent().propose(ctx, BIG)
    assert p.days[0].items == [] and "Travel day" in p.days[0].notes
    empty = await ActivitiesAgent().propose(await make_ctx(attractions=[]), BIG)
    assert empty.cost == 0 and "Free day" in empty.days[1].notes


async def test_llm_adds_theme_and_tip_but_cannot_change_places(monkeypatch):
    ctx = await make_ctx()
    before = await ActivitiesAgent().propose(ctx, BIG, narrate=False)
    monkeypatch.setattr("app.agents.base.chat_json", fake_llm({"days": [
        {"day": 1, "theme": "Old town stroll", "tip": "Start early to beat crowds."},
        {"day": 99, "theme": "ghost", "tip": "ignored"}, "junk",
        {"day": 2, "places": ["Invented Place"]}]}))
    after = await ActivitiesAgent().propose(ctx, BIG)
    assert after.used_llm and "Old town stroll" in after.days[0].notes
    assert [i.name for d in after.days for i in d.items] == [i.name for d in before.days for i in d.items]
    assert not any("ghost" in (d.notes or "") for d in after.days)


async def test_unusable_llm_answers_are_ignored(monkeypatch):
    for bad in ({"days": "nope"}, {"other": 1}, None):
        monkeypatch.setattr("app.agents.base.chat_json", fake_llm(bad))
        p = await ActivitiesAgent().propose(await make_ctx(), BIG)
        assert not p.used_llm and p.cost >= 0
