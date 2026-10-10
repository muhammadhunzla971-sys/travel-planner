from datetime import date, timedelta

import pytest

from app.models import TravelStyle, TripPreferences
from app.services.budget import allocate_budget, cap_category, shift_budget
from tests.conftest import make_request


def _nights(n: int):
    start = date.today() + timedelta(days=20)
    return {"start_date": start, "end_date": start + timedelta(days=n)}


def test_allocation_sums_exactly_to_budget():
    for budget in (999.99, 2000, 12345.67, 1):
        a = allocate_budget(make_request(budget=budget))
        assert a.allocated() == pytest.approx(a.total, abs=0.01)
        assert all(v >= 0 for v in a.amounts().values())


def test_default_split_is_about_base():
    a = allocate_budget(make_request(**_nights(6)))
    p = a.percentages()
    assert p["flights"] == 35.0 and p["stays"] == 35.0
    assert p["activities"] == 15.0 and p["food_transport"] == 10.0 and p["buffer"] == 5.0


def test_luxury_gives_more_to_stays_than_budget_style():
    lux = allocate_budget(make_request(preferences=TripPreferences(style=TravelStyle.luxury)))
    cheap = allocate_budget(make_request(preferences=TripPreferences(style=TravelStyle.budget)))
    assert lux.stays > cheap.stays


def test_short_trip_gives_flights_bigger_share_than_long_trip():
    short = allocate_budget(make_request(**_nights(2)))
    long_ = allocate_budget(make_request(**_nights(12)))
    assert short.flights > long_.flights
    assert long_.stays > short.stays


def test_cost_level_changes_split():
    low = allocate_budget(make_request(), cost_level="low")
    high = allocate_budget(make_request(), cost_level="high")
    assert low.flights > high.flights
    assert high.stays > low.stays


def test_shift_budget_keeps_total():
    a = allocate_budget(make_request())
    b = shift_budget(a, "flights", "activities", 100)
    assert b.flights == pytest.approx(a.flights - 100)
    assert b.activities == pytest.approx(a.activities + 100)
    assert b.allocated() == pytest.approx(a.total, abs=0.01)


def test_shift_budget_rejects_bad_input():
    a = allocate_budget(make_request())
    with pytest.raises(ValueError):
        shift_budget(a, "flights", "stays", a.flights + 1)
    with pytest.raises(ValueError):
        shift_budget(a, "flights", "nope", 10)


def test_cap_category_releases_money_and_keeps_total():
    a = allocate_budget(make_request(budget=2000))
    cap = a.flights - 150
    b = cap_category(a, "flights", cap)
    assert b.flights == pytest.approx(cap)
    assert b.stays > a.stays and b.activities > a.activities
    assert b.allocated() == pytest.approx(a.total, abs=0.01)


def test_cap_above_current_changes_nothing():
    a = allocate_budget(make_request())
    assert cap_category(a, "flights", a.flights + 500) == a
