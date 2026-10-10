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


def wiki_pages(*items):
    pages = []
    for title, extract, lat, lon in items:
        page = {"title": title, "extract": extract}
        if lat is not None:
            page["coordinates"] = [{"lat": lat, "lon": lon}]
        pages.append(page)
    return {"query": {"pages": pages}}


LONG = "A famous landmark that many visitors come to see every year."
WIKI_ISTANBUL = wiki_pages(
    ("Hagia Sophia Museum", LONG, 41.0086, 28.9802),
    ("Topkapi Palace", LONG, 41.0115, 28.9834),
    ("Galata Tower", LONG, 41.0256, 28.9744),
    ("Blue Mosque", LONG, 41.0054, 28.9768),
    ("Gulhane Park", LONG, 41.0131, 28.9814),
    ("Istanbul University", LONG, 41.0128, 28.9636),   # skipped: not an attraction
    ("Some Short Page", "tiny", 41.01, 28.98),          # skipped: extract too short
    ("No Coordinates Place", LONG, None, None),         # skipped: no coords
)

FUTURE_START = date(2030, 1, 10)
