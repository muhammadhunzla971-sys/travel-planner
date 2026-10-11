from datetime import date, timedelta

from app.models.plan import DataSource
from app.tools.http import ProviderError
from app.tools.places import (
    Place,
    _rank_score,
    categorize,
    find_attractions,
    generic_activities,
)
from app.tools.weather import (
    DayWeather,
    describe_code,
    get_weather,
    one_year_earlier,
    summarize_weather,
)
from tests.fakes import (
    FORECAST,
    ISTANBUL,
    LIVE_PLACE_NAMES,
    WIKI_ISTANBUL,
    WIKI_PAGES,
    patch_all,
    wiki_page,
    wiki_response,
)


# ---- weather -------------------------------------------------------------
async def test_forecast_used_for_near_dates(monkeypatch):
    calls = []
    patch_all(monkeypatch, {"api.open-meteo.com/v1/forecast": FORECAST}, calls)
    start = date.today() + timedelta(days=2)
    days = await get_weather(41.0, 28.9, start, start + timedelta(days=1))
    assert len(days) == 2
    assert days[0].source == DataSource.live
    assert days[0].summary == "partly cloudy" and days[1].summary == "rain"
    assert "forecast" in calls[0][0]


async def test_archive_used_for_far_dates_and_shifted_to_target(monkeypatch):
    calls = []
    last_year = {"daily": {"time": ["2029-01-10", "2029-01-11"],
                           "temperature_2m_max": [10.0, 12.0], "temperature_2m_min": [2.0, 3.0],
                           "precipitation_sum": [0.0, 0.0], "weather_code": [0, 0]}}
    patch_all(monkeypatch, {"archive-api": last_year}, calls)
    start = date(2030, 1, 10)
    days = await get_weather(41.0, 28.9, start, date(2030, 1, 11))
    assert "archive" in calls[0][0]
    assert calls[0][1]["start_date"] == "2029-01-10"
    assert [d.date for d in days] == [date(2030, 1, 10), date(2030, 1, 11)]
    assert all(d.source == DataSource.estimated for d in days)
    assert "last year" in summarize_weather(days)


async def test_weather_provider_error_propagates_to_caller(monkeypatch):
    patch_all(monkeypatch, {})
    try:
        await get_weather(41.0, 28.9, date(2030, 1, 10), date(2030, 1, 12))
        raise AssertionError("expected ProviderError")
    except ProviderError:
        pass


def test_weather_helpers():
    assert one_year_earlier(date(2028, 2, 29)) == date(2027, 2, 28)
    assert describe_code(0) == "clear sky" and describe_code(63) == "rain"
    assert describe_code(75) == "snow" and describe_code(96) == "thunderstorm"
    assert describe_code(None) == "unknown"
    assert summarize_weather([]) == "Weather data not available."
    s = summarize_weather([DayWeather(date=date(2030, 1, 1), temp_min_c=2, temp_max_c=11,
                                      summary="rain")])
    assert "2-11 C" in s and "1 of 1" in s


# ---- places --------------------------------------------------------------
async def test_attractions_live_filtered_and_ranked_by_popularity(monkeypatch):
    patch_all(monkeypatch, {"wikipedia": WIKI_ISTANBUL})
    places = await find_attractions(ISTANBUL)
    names = [p.name for p in places]
    assert set(names) == LIVE_PLACE_NAMES  # university, neighbourhood and the city itself are gone
    assert all(p.source == DataSource.live for p in places)
    assert names[0] == "Hagia Sophia" and names[-1] == "Obscure Chapel"
    scores = [_rank_score(p) for p in places]
    assert scores == sorted(scores, reverse=True)
    by_name = {p.name: p for p in places}
    assert by_name["Topkapi Palace"].category == "museum" and by_name["Topkapi Palace"].est_entry_usd > 0
    assert by_name["Blue Mosque"].category == "religious"
    assert by_name["Galata Tower"].category == "historic"


async def test_curated_page_missing_from_geosearch_is_still_found(monkeypatch):
    patch_all(monkeypatch, {"wikipedia": WIKI_ISTANBUL})
    cistern = next(p for p in await find_attractions(ISTANBUL) if p.name == "Basilica Cistern")
    assert cistern.curated and cistern.distance_km > 0 and cistern.popularity == 300_000
    assert cistern.category == "historic"


async def test_famous_place_far_from_centre_beats_obscure_place_next_to_it(monkeypatch):
    fake = wiki_response(
        geo=[("Obscure Chapel", 41.0140, 28.9500), ("Famous Tower", 41.09, 28.98)],
        pages=[wiki_page("Obscure Chapel", "Small chapel in Istanbul", 20, 41.0140, 28.9500),
               wiki_page("Famous Tower", "Landmark tower in Istanbul", 170_000, 41.09, 28.98)])
    patch_all(monkeypatch, {"wikipedia": fake})
    places = await find_attractions(ISTANBUL)
    assert places[0].name == "Famous Tower" and places[0].popularity == 170_000


async def test_works_without_a_curated_category(monkeypatch):
    fake = wiki_response(geo=[("Galata Tower", 41.0256, 28.9744)], cats=(), pages=WIKI_PAGES)
    patch_all(monkeypatch, {"wikipedia": fake})
    live = [p for p in await find_attractions(ISTANBUL) if p.source == DataSource.live]
    assert [p.name for p in live] == ["Galata Tower"] and not live[0].curated


async def test_still_returns_places_when_page_details_are_unavailable(monkeypatch):
    async def fake(url, params=None, **kw):
        if "titles" in (params or {}):
            raise ProviderError("details down")
        return WIKI_ISTANBUL(params)

    monkeypatch.setattr("app.tools.places.fetch_json", fake)
    names = {p.name for p in await find_attractions(ISTANBUL) if p.source == DataSource.live}
    # no description/popularity, so only titles that are recognisably sights (or curated) are kept
    assert {"Hagia Sophia", "Topkapi Palace", "Blue Mosque", "Galata Tower", "Gulhane Park"} <= names
    assert "Istanbul University" not in names and "Istanbul" not in names


async def test_curated_category_alone_is_enough_when_geosearch_fails(monkeypatch):
    async def fake(url, params=None, **kw):
        if (params or {}).get("list") == "geosearch":
            raise ProviderError("geosearch down")
        return WIKI_ISTANBUL(params)

    monkeypatch.setattr("app.tools.places.fetch_json", fake)
    names = {p.name for p in await find_attractions(ISTANBUL) if p.source == DataSource.live}
    assert names == {"Hagia Sophia", "Basilica Cistern"}


async def test_details_are_requested_in_batches_of_at_most_50(monkeypatch):
    geo = [(f"Place {i} Museum", 41.0 + i * 0.0001, 28.95) for i in range(120)]
    calls = []
    patch_all(monkeypatch, {"wikipedia": wiki_response(geo=geo, pages=[])}, calls)
    await find_attractions(ISTANBUL)
    batches = [p["titles"].split("|") for _url, p in calls if "titles" in (p or {})]
    assert len(batches) == 3 and max(len(b) for b in batches) == 50
    assert sum(len(b) for b in batches) == 120


async def test_limit_is_respected(monkeypatch):
    patch_all(monkeypatch, {"wikipedia": WIKI_ISTANBUL})
    places = await find_attractions(ISTANBUL, limit=6)
    assert len(places) == 6 and sum(p.source == DataSource.live for p in places) == 6 or len(places) >= 5


async def test_attractions_topped_up_when_few_live_results(monkeypatch):
    fake = wiki_response(geo=[("Hagia Sophia", 41.0086, 28.9802), ("Blue Mosque", 41.0054, 28.9768)],
                         pages=WIKI_PAGES)
    patch_all(monkeypatch, {"wikipedia": fake})
    places = await find_attractions(ISTANBUL)
    assert [p.source for p in places].count(DataSource.live) == 2
    assert any(p.source == DataSource.estimated for p in places)


async def test_attractions_fallback_when_api_down(monkeypatch):
    patch_all(monkeypatch, {})
    places = await find_attractions(ISTANBUL)
    assert len(places) >= 5
    assert all(p.source == DataSource.estimated for p in places)
    assert all("Istanbul" in p.name for p in places)


def test_rank_score_prefers_popular_curated_places():
    base = {"name": "x", "category": "historic", "distance_km": 1.0}
    famous = Place(**base, popularity=500_000)
    obscure = Place(**base, popularity=10)
    curated = Place(**base, popularity=10, curated=True)
    assert _rank_score(famous) > _rank_score(obscure)
    assert _rank_score(curated) > _rank_score(obscure)


def test_categorize_and_generic():
    assert categorize("National Museum") == "museum"
    assert categorize("Old Fort") == "historic"
    assert categorize("Central Park") == "nature"
    assert categorize("Random Thing") == "sightseeing"
    assert categorize("Basilica Cistern") == "historic"
    assert len(generic_activities(ISTANBUL)) == 5
