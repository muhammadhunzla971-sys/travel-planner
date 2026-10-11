"""Helpers to fake external APIs in tests (no real network needed)."""
from datetime import date

from app.models.plan import DataSource
from app.tools.currency import Rate
from app.tools.geo import GeoPoint
from app.tools.http import ProviderError

PATCH_TARGETS = (
    "app.tools.geo.fetch_json",
    "app.tools.currency.fetch_json",
    "app.tools.weather.fetch_json",
    "app.tools.places.fetch_json",
    "app.tools.restaurants.fetch_json",
)


def make_fetch(routes: dict[str, object], calls: list | None = None):
    """routes maps a URL substring -> response dict, or an Exception to raise.
    Unknown URLs raise ProviderError (like a provider being down)."""

    async def fake(url, params=None, **kwargs):
        if calls is not None:
            calls.append((url, params))
        for fragment, response in routes.items():
            if fragment in url:
                if isinstance(response, Exception):
                    raise response
                if callable(response):
                    return response(params)
                return response
        raise ProviderError(f"no fake route for {url}")

    return fake


def patch_all(monkeypatch, routes: dict[str, object], calls: list | None = None) -> None:
    fake = make_fetch(routes, calls)
    for target in PATCH_TARGETS:
        monkeypatch.setattr(target, fake)


def all_down(monkeypatch) -> None:
    patch_all(monkeypatch, {})


def geopoint(name: str, cc: str, lat: float, lon: float, tz: str) -> GeoPoint:
    return GeoPoint(name=name, country_code=cc, latitude=lat, longitude=lon, timezone=tz,
                    source=DataSource.live)


LAHORE = geopoint("Lahore", "PK", 31.55, 74.34, "Asia/Karachi")
ISLAMABAD = geopoint("Islamabad", "PK", 33.69, 73.05, "Asia/Karachi")
ISTANBUL = geopoint("Istanbul", "TR", 41.01, 28.98, "Europe/Istanbul")
LONDON = geopoint("London", "GB", 51.51, -0.13, "Europe/London")

USD_TO_USD = Rate(base="USD", quote="USD", rate=1.0, source=DataSource.live, provider="test")
USD_TO_PKR = Rate(base="USD", quote="PKR", rate=280.0, source=DataSource.live, provider="test")

GEOCODE_ISTANBUL = {"results": [{
    "name": "Istanbul", "country": "Turkey", "country_code": "TR", "admin1": "Istanbul",
    "latitude": 41.01384, "longitude": 28.94966, "timezone": "Europe/Istanbul"}]}
GEOCODE_LAHORE = {"results": [{
    "name": "Lahore", "country": "Pakistan", "country_code": "PK", "admin1": "Punjab",
    "latitude": 31.558, "longitude": 74.35071, "timezone": "Asia/Karachi"}]}
ER_API = {"result": "success", "rates": {"USD": 1, "PKR": 280.0, "EUR": 0.9, "TRY": 40.0}}

FORECAST = {"daily": {
    "time": ["2026-10-12", "2026-10-13"],
    "temperature_2m_max": [22.0, 24.5], "temperature_2m_min": [14.0, 15.5],
    "precipitation_sum": [0.0, 3.2], "weather_code": [1, 61]}}


def wiki_page(title, desc="", views=None, lat=None, lon=None):
    """One page as returned by the Wikipedia 'details' query."""
    page = {"title": title}
    if desc:
        page["description"] = desc
    if views is not None:
        page["pageviews"] = {"2026-09-01": views}
    if lat is not None:
        page["coordinates"] = [{"lat": lat, "lon": lon}]
    return page


def wiki_response(geo=(), cats=(), pages=()):
    """Fake Wikipedia API. Answers the three kinds of request by their params:
    list=geosearch, list=categorymembers and the batched title details."""
    by_title = {p["title"]: p for p in pages}
    geo_rows = [{"pageid": i, "ns": 0, "title": t, "lat": lat, "lon": lon, "dist": 100.0 * i}
                for i, (t, lat, lon) in enumerate(geo, 1)]
    cat_rows = [{"pageid": i, "ns": 0, "title": t} for i, t in enumerate(cats, 1)]

    def respond(params):
        p = params or {}
        if p.get("list") == "geosearch":
            return {"query": {"geosearch": geo_rows}}
        if p.get("list") == "categorymembers":
            return {"query": {"categorymembers": cat_rows}}
        titles = (p.get("titles") or "").split("|")
        return {"query": {"pages": [by_title[t] for t in titles if t in by_title]}}

    return respond


WIKI_GEO = [
    ("Hagia Sophia", 41.0086, 28.9802), ("Topkapi Palace", 41.0115, 28.9834),
    ("Galata Tower", 41.0256, 28.9744), ("Blue Mosque", 41.0054, 28.9768),
    ("Gulhane Park", 41.0131, 28.9814), ("Obscure Chapel", 41.0140, 28.9500),
    ("Istanbul University", 41.0128, 28.9636),  # skipped: not an attraction (title)
    ("Aksaray, Fatih", 41.0100, 28.9528),       # skipped: a neighbourhood (description)
    ("Istanbul", 41.0100, 28.9500),             # skipped: the city itself
]
WIKI_PAGES = [
    wiki_page("Hagia Sophia", "Mosque and former church in Istanbul", 900_000, 41.0086, 28.9802),
    wiki_page("Topkapi Palace", "Museum and former palace in Istanbul", 500_000, 41.0115, 28.9834),
    wiki_page("Galata Tower", "Medieval tower in Istanbul", 400_000, 41.0256, 28.9744),
    wiki_page("Blue Mosque", "Mosque in Istanbul, Turkey", 600_000, 41.0054, 28.9768),
    wiki_page("Gulhane Park", "Historic urban park in Istanbul", 50_000, 41.0131, 28.9814),
    wiki_page("Obscure Chapel", "Small chapel in Istanbul", 20, 41.0140, 28.9500),
    wiki_page("Istanbul University", "Public university in Istanbul", 80_000, 41.0128, 28.9636),
    wiki_page("Aksaray, Fatih", "Neighbourhood in Fatih, Istanbul", 3_000, 41.0100, 28.9528),
    wiki_page("Istanbul", "Largest city in Turkey", 9_000_000, 41.0100, 28.9500),
    # only in the curated category list, NOT in the geosearch results:
    wiki_page("Basilica Cistern", "Underground cistern in Istanbul", 300_000, 41.0084, 28.9778),
]
WIKI_ISTANBUL = wiki_response(geo=WIKI_GEO, cats=["Hagia Sophia", "Basilica Cistern"], pages=WIKI_PAGES)
LIVE_PLACE_NAMES = {"Hagia Sophia", "Topkapi Palace", "Galata Tower", "Blue Mosque", "Gulhane Park",
                    "Obscure Chapel", "Basilica Cistern"}

FUTURE_START = date(2030, 1, 10)
