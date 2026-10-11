from datetime import date, timedelta

from app.models.plan import DataSource
from app.tools.http import ProviderError
from app.tools.places import (
    MIN_GOOD_PLACES,
    Place,
    _rank_score,
    _sample_points,
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


async def test_curated_category_alone_is_enough_when_geosearch_fails(monkeypatch):
    async def fake(url, params=None, **kw):
        if (params or {}).get("list") == "geosearch":
            raise ProviderError("geosearch down")
        return WIKI_ISTANBUL(params)

    monkeypatch.setattr("app.tools.places.fetch_json", fake)
    names = {p.name for p in await find_attractions(ISTANBUL) if p.source == DataSource.live}
    assert names == {"Hagia Sophia", "Basilica Cistern"}


async def test_details_are_requested_in_batches_of_at_most_50(monkeypatch):
    geo = [(f"Place {chr(65 + i // 26)}{chr(65 + i % 26)} Museum", 41.0 + i * 0.0001, 28.95) for i in range(120)]
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


def test_sample_points_cover_a_wide_area():
    pts = _sample_points(ISTANBUL)
    assert len(pts) == 9 and len(set(pts)) == 9
    assert pts[0] == (ISTANBUL.latitude, ISTANBUL.longitude)


async def test_geosearch_runs_at_many_points_and_dedupes(monkeypatch):
    calls = []
    patch_all(monkeypatch, {"wikipedia": WIKI_ISTANBUL}, calls)
    places = await find_attractions(ISTANBUL)
    geo_calls = [p for _u, p in calls if (p or {}).get("list") == "geosearch"]
    assert len(geo_calls) == 9 and len({p["gscoord"] for p in geo_calls}) == 9
    names = [p.name for p in places]
    assert len(names) == len(set(names))  # same page found from several points counted once


async def test_geosearch_partial_failure_is_tolerated(monkeypatch):
    state = {"n": 0}

    async def fake(url, params=None, **kw):
        if (params or {}).get("list") == "geosearch":
            state["n"] += 1
            if state["n"] % 2 == 0:
                raise ProviderError("flaky")
        return WIKI_ISTANBUL(params)

    monkeypatch.setattr("app.tools.places.fetch_json", fake)
    names = {p.name for p in await find_attractions(ISTANBUL) if p.source == DataSource.live}
    assert "Hagia Sophia" in names


async def test_event_and_year_pages_are_not_attractions(monkeypatch):
    geo = [("Hagia Sophia", 41.0086, 28.9802), ("1999 Izmit earthquake", 41.0, 28.9),
           ("Istanbul bombings", 41.0, 28.9), ("List of mosques in Istanbul", 41.0, 28.9),
           ("Sultanahmet Incident", 41.0, 28.9), ("Great Fire of Constantinople", 41.0, 28.9)]
    pages = [wiki_page("Hagia Sophia", "Mosque in Istanbul", 900_000, 41.0086, 28.9802)] + [
        wiki_page(t, "Museum of something", 90_000, 41.0, 28.9) for t, *_ in geo[1:]]
    patch_all(monkeypatch, {"wikipedia": wiki_response(geo=geo, pages=pages)})
    live = [p.name for p in await find_attractions(ISTANBUL) if p.source == DataSource.live]
    assert live == ["Hagia Sophia"]


async def test_description_marking_an_event_is_filtered(monkeypatch):
    geo = [("Hagia Sophia", 41.0086, 28.9802), ("Sultanahmet Explosion", 41.0, 28.9)]
    pages = [wiki_page("Hagia Sophia", "Mosque in Istanbul", 900_000, 41.0086, 28.9802),
             wiki_page("Sultanahmet Explosion", "2016 terrorist attack in Istanbul museum", 50_000, 41.0, 28.9)]
    patch_all(monkeypatch, {"wikipedia": wiki_response(geo=geo, pages=pages)})
    live = [p.name for p in await find_attractions(ISTANBUL) if p.source == DataSource.live]
    assert live == ["Hagia Sophia"]


async def test_obscure_pages_dropped_when_enough_good_places_exist(monkeypatch):
    names = [f"Great Museum {c}" for c in "ABCDEFGHIJ"]
    geo = [(n, 41.0 + i * 0.001, 28.95) for i, n in enumerate(names)] + [("Tiny Chapel", 41.02, 28.95)]
    pages = [wiki_page(n, "Museum in Istanbul", 50_000, 41.0, 28.95) for n in names]
    pages.append(wiki_page("Tiny Chapel", "Small chapel in Istanbul", 40, 41.02, 28.95))
    patch_all(monkeypatch, {"wikipedia": wiki_response(geo=geo, pages=pages)})
    live = {p.name for p in await find_attractions(ISTANBUL) if p.source == DataSource.live}
    assert "Tiny Chapel" not in live and len(live) == 10


async def test_obscure_pages_backfill_when_too_few_good_places(monkeypatch):
    geo = [("Great Museum", 41.0, 28.95), ("Tiny Chapel", 41.02, 28.95), ("Small Church", 41.03, 28.95)]
    pages = [wiki_page("Great Museum", "Museum in Istanbul", 50_000, 41.0, 28.95),
             wiki_page("Tiny Chapel", "Small chapel in Istanbul", 40, 41.02, 28.95),
             wiki_page("Small Church", "Church in Istanbul", 30, 41.03, 28.95)]
    patch_all(monkeypatch, {"wikipedia": wiki_response(geo=geo, pages=pages)})
    live = [p.name for p in await find_attractions(ISTANBUL) if p.source == DataSource.live]
    assert live[0] == "Great Museum" and len(live) == 3 and MIN_GOOD_PLACES >= 3


async def test_diagnose_reports_why_places_are_kept_or_dropped(monkeypatch):
    from app.tools.places import diagnose
    patch_all(monkeypatch, {"wikipedia": WIKI_ISTANBUL})
    rep = await diagnose(ISTANBUL, check=("Hagia Sophia", "Istanbul University", "Nowhere Tower"))
    assert rep["geosearch"]["points"] == 9 and rep["geosearch"]["points_failed"] == 0
    assert rep["checks"]["Hagia Sophia"]["rejected_because"] is None
    assert rep["checks"]["Hagia Sophia"]["views_30d"] == 900_000
    assert rep["checks"]["Istanbul University"]["rejected_because"] == "title_filter"
    assert rep["checks"]["Nowhere Tower"]["rejected_because"] == "not_returned_by_wikipedia"
    assert rep["top"][0]["name"] == "Hagia Sophia"


async def test_diagnose_shows_failed_detail_batches(monkeypatch):
    from app.tools.places import diagnose

    async def fake(url, params=None, **kw):
        if "titles" in (params or {}):
            raise ProviderError("429")
        return WIKI_ISTANBUL(params)

    monkeypatch.setattr("app.tools.places.fetch_json", fake)
    rep = await diagnose(ISTANBUL)
    assert rep["details"]["batches_failed"] == rep["details"]["batches"] >= 1
    assert rep["details"]["with_views"] == 0


async def test_all_detail_batches_failing_is_an_error_not_a_cached_result(monkeypatch):
    async def fake(url, params=None, **kw):
        if "titles" in (params or {}):
            raise ProviderError("429")
        return WIKI_ISTANBUL(params)

    monkeypatch.setattr("app.tools.places.fetch_json", fake)
    places = await find_attractions(ISTANBUL)
    assert all(p.source == DataSource.estimated for p in places)  # honest generic fallback


async def test_details_follow_continuation_so_coordinates_are_not_lost(monkeypatch):
    calls = []

    async def fake(url, params=None, **kw):
        p = params or {}
        calls.append(p)
        if p.get("list") == "geosearch":
            return {"query": {"geosearch": []}}
        if p.get("list") == "categorymembers":
            return {"query": {"categorymembers": [{"title": "Galata Tower"}]}}
        if "cocontinue" not in p:  # part 1: description + views, no coordinates yet
            return {"continue": {"cocontinue": "x", "continue": "||"},
                    "query": {"pages": [{"title": "Galata Tower", "description": "Tower in Istanbul",
                                         "pageviews": {"2026-09-01": 5000}}]}}
        return {"query": {"pages": [{"title": "Galata Tower",
                                     "coordinates": [{"lat": 41.0256, "lon": 28.9744}]}]}}

    monkeypatch.setattr("app.tools.places.fetch_json", fake)
    live = [p for p in await find_attractions(ISTANBUL) if p.source == DataSource.live]
    assert [p.name for p in live] == ["Galata Tower"]
    assert live[0].popularity == 5000 and live[0].latitude == 41.0256


async def test_history_pages_and_government_terms_are_not_sights(monkeypatch):
    geo = [("Hagia Sophia", 41.0086, 28.9802), ("Sack of Constantinople", 41.0, 28.9),
           ("Sublime Porte", 41.0, 28.9), ("Byzantium", 41.0, 28.9), ("Golden Horn", 41.0, 28.9)]
    pages = [wiki_page("Hagia Sophia", "Mosque in Istanbul", 900_000, 41.0086, 28.9802),
             wiki_page("Sack of Constantinople", "Event", 90_000, 41.0, 28.9),
             wiki_page("Sublime Porte", "Government of the Ottoman Empire", 90_000, 41.0, 28.9),
             wiki_page("Byzantium", "Ancient Greek colony, predecessor of Istanbul", 90_000, 41.0, 28.9),
             wiki_page("Golden Horn", "Inlet of the Bosphorus in Istanbul", 90_000, 41.0, 28.9)]
    patch_all(monkeypatch, {"wikipedia": wiki_response(geo=geo, pages=pages)})
    live = [p.name for p in await find_attractions(ISTANBUL) if p.source == DataSource.live]
    assert live == ["Hagia Sophia"]


async def test_byzantium_is_dropped_whatever_wikipedia_calls_it(monkeypatch):
    geo = [("Hagia Sophia", 41.0086, 28.9802), ("Byzantium", 41.0, 28.9), ("Lost City", 41.0, 28.9),
           ("Hippodrome of Constantinople", 41.0054, 28.9753)]
    pages = [wiki_page("Hagia Sophia", "Mosque in Istanbul", 900_000, 41.0086, 28.9802),
             wiki_page("Byzantium", "", 90_000, 41.0, 28.9),                       # no description at all
             wiki_page("Lost City", "Ancient Greek city on the Bosphorus", 90_000, 41.0, 28.9),
             wiki_page("Hippodrome of Constantinople", "Ancient Roman chariot racing stadium",
                       80_000, 41.0054, 28.9753)]                                    # a real sight: kept
    patch_all(monkeypatch, {"wikipedia": wiki_response(geo=geo, pages=pages)})
    live = {p.name for p in await find_attractions(ISTANBUL) if p.source == DataSource.live}
    assert live == {"Hagia Sophia", "Hippodrome of Constantinople"}
