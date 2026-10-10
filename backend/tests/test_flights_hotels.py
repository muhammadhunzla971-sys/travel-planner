from datetime import date, timedelta

from app.models import TravelStyle, TripPreferences
from app.models.plan import DataSource
from app.tools.cost_index import (
    cost_level,
    food_transport_usd_per_day,
    price_multiplier,
)
from app.tools.flights import search_flights, season_factor
from app.tools.hotels import search_stays
from tests.conftest import make_request
from tests.fakes import ISLAMABAD, ISTANBUL, LAHORE, LONDON, USD_TO_PKR, USD_TO_USD


# ---- flights -------------------------------------------------------------
async def test_flights_three_options_sorted_and_estimated():
    req = make_request()
    flights = await search_flights(req, LAHORE, ISTANBUL, USD_TO_USD)
    assert len(flights) == 3
    prices = [f.total_price for f in flights]
    assert prices == sorted(prices)
    assert all(f.source == DataSource.estimated for f in flights)
    direct = next(f for f in flights if f.id == "est-direct")
    assert direct.stops == 0 and direct.total_price == max(prices)
    assert all("estimate" in f.airline for f in flights)


async def test_flights_dates_match_request():
    req = make_request()
    for f in await search_flights(req, LAHORE, ISTANBUL, USD_TO_USD):
        assert f.depart_at.date() == req.start_date
        assert f.return_depart_at.date() == req.end_date
        assert f.arrive_at > f.depart_at and f.return_arrive_at > f.return_depart_at


async def test_flights_scale_with_travelers_and_currency():
    one = (await search_flights(make_request(travelers=1), LAHORE, ISTANBUL, USD_TO_USD))[0]
    two = (await search_flights(make_request(travelers=2), LAHORE, ISTANBUL, USD_TO_USD))[0]
    assert two.total_price == round(one.total_price * 2, 2) or abs(two.total_price - 2 * one.total_price) < 0.02
    pkr = (await search_flights(make_request(travelers=1), LAHORE, ISTANBUL, USD_TO_PKR))[0]
    assert pkr.currency == "PKR" and abs(pkr.total_price - one.total_price * 280) < 1


async def test_flights_short_route_has_no_stops_and_is_cheaper():
    req = make_request()
    short = await search_flights(req, LAHORE, ISLAMABAD, USD_TO_USD)
    long_ = await search_flights(req, LAHORE, LONDON, USD_TO_USD)
    assert all(f.stops == 0 for f in short)
    assert short[0].total_price < long_[0].total_price
    assert any(f.stops >= 1 for f in long_)


async def test_flights_need_an_origin():
    assert await search_flights(make_request(), None, ISTANBUL, USD_TO_USD) == []


def test_season_factor():
    today = date(2030, 1, 1)
    assert season_factor(date(2030, 4, 20), today) == 1.0
    assert season_factor(date(2030, 7, 20), today) == 1.15
    assert season_factor(date(2030, 1, 5), today) == 1.2  # last minute


# ---- hotels --------------------------------------------------------------
async def test_stays_tiers_sorted_and_totals_match():
    req = make_request()
    stays = await search_stays(req, ISTANBUL, USD_TO_USD)
    assert stays[0].kind == "hostel"
    totals = [s.total_price for s in stays]
    assert totals == sorted(totals)
    for s in stays:
        assert s.nights == req.nights
        assert abs(s.total_price - s.price_per_night * req.nights) < 0.02
        assert s.source == DataSource.estimated and s.rating is None
        assert "(estimate)" in s.name


async def test_stays_rooms_depend_on_travelers():
    one = await search_stays(make_request(travelers=1), ISTANBUL, USD_TO_USD)
    four = await search_stays(make_request(travelers=4), ISTANBUL, USD_TO_USD)
    hotel1 = next(s for s in one if s.id == "est-mid").price_per_night
    hotel4 = next(s for s in four if s.id == "est-mid").price_per_night
    assert hotel4 == hotel1 * 2  # 4 people = 2 rooms, 1 person = 1 room
    hostel1 = next(s for s in one if s.id == "est-hostel").price_per_night
    hostel4 = next(s for s in four if s.id == "est-hostel").price_per_night
    assert hostel4 == hostel1 * 4  # hostel is priced per bed


async def test_stays_respect_min_stars_and_country_prices():
    req = make_request(preferences=TripPreferences(min_hotel_stars=3))
    stays = await search_stays(req, ISTANBUL, USD_TO_USD)
    assert {s.id for s in stays} == {"est-mid", "est-upscale"}
    cheap = await search_stays(make_request(), ISLAMABAD, USD_TO_USD)
    pricey = await search_stays(make_request(), LONDON, USD_TO_USD)
    assert cheap[0].total_price < pricey[0].total_price


# ---- cost index ----------------------------------------------------------
def test_cost_index_helpers():
    assert price_multiplier("PK") < price_multiplier("GB")
    assert price_multiplier(None) == price_multiplier("ZZ") == 1.0
    assert cost_level("PK") == "low" and cost_level("GB") == "high" and cost_level("ES") == "medium"
    budget = food_transport_usd_per_day("TR", TravelStyle.budget)
    luxury = food_transport_usd_per_day("TR", TravelStyle.luxury)
    assert budget < luxury


def test_date_helpers_still_sane():
    assert (date.today() + timedelta(days=30)) > date.today()
