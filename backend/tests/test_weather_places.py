from datetime import date, timedelta

from app.models.plan import DataSource
from app.tools.http import ProviderError
from app.tools.places import (
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
from tests.fakes import FORECAST, ISTANBUL, LONG, WIKI_ISTANBUL, patch_all, wiki_pages


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
async def test_attractions_live_filtered_and_sorted(monkeypatch):
    patch_all(monkeypatch, {"wikipedia": WIKI_ISTANBUL})
    places = await find_attractions(ISTANBUL)
    names = [p.name for p in places]
    assert "Istanbul University" not in names
    assert "Some Short Page" not in names and "No Coordinates Place" not in names
    assert len(places) == 5 and all(p.source == DataSource.live for p in places)
    scores = [_rank_score(p) for p in places]
    assert scores == sorted(scores, reverse=True)
    by_name = {p.name: p for p in places}
    assert by_name["Hagia Sophia Museum"].category == "museum"
    assert by_name["Hagia Sophia Museum"].est_entry_usd > 0
    assert by_name["Blue Mosque"].category == "religious"


async def test_popular_far_place_beats_obscure_near_place(monkeypatch):
    data = wiki_pages(("Obscure Chapel", LONG, 41.0140, 28.9500), ("Famous Tower", LONG, 41.09, 28.98))
    pages = data["query"]["pages"]
    pages[0]["pageviews"] = {"2026-09-01": 20}
    pages[1]["pageviews"] = {"2026-09-01": 90000, "2026-09-02": 80000}
    patch_all(monkeypatch, {"wikipedia": data})
    places = await find_attractions(ISTANBUL)
    assert places[0].name == "Famous Tower" and places[0].popularity == 170000


async def test_city_itself_and_neighbourhoods_are_not_attractions(monkeypatch):
    data = wiki_pages(
        ("Istanbul", "Istanbul is the largest city in Turkey and a megacity of many people.", 41.01, 28.95),
        ("Aksaray, Fatih", "Aksaray is a neighbourhood in the municipality of Fatih, Istanbul.", 41.01, 28.95),
        ("Galata Tower", LONG, 41.0256, 28.9744))
    patch_all(monkeypatch, {"wikipedia": data})
    names = [p.name for p in await find_attractions(ISTANBUL) if p.source.value == "live"]
    assert names == ["Galata Tower"]


async def test_attractions_topped_up_when_few_live_results(monkeypatch):
    few = {"query": {"pages": WIKI_ISTANBUL["query"]["pages"][:2]}}
    patch_all(monkeypatch, {"wikipedia": few})
    places = await find_attractions(ISTANBUL)
    assert [p.source for p in places].count(DataSource.live) == 2
    assert any(p.source == DataSource.estimated for p in places)


async def test_attractions_fallback_when_api_down(monkeypatch):
    patch_all(monkeypatch, {})
    places = await find_attractions(ISTANBUL)
    assert len(places) >= 5
    assert all(p.source == DataSource.estimated for p in places)
    assert all("Istanbul" in p.name for p in places)


def test_categorize_and_generic():
    assert categorize("National Museum") == "museum"
    assert categorize("Old Fort") == "historic"
    assert categorize("Central Park") == "nature"
    assert categorize("Random Thing") == "sightseeing"
    assert len(generic_activities(ISTANBUL)) == 5
