"""Geocoding (city name -> coordinates) and distances.

Live provider: Open-Meteo geocoding (free, no key).
Fallback: a small built-in table of popular cities, used when the API is down.
"""
import math

from pydantic import BaseModel

from app.models.plan import DataSource
from app.tools.cache import cache, make_key
from app.tools.http import ProviderError, fetch_json

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
GEOCODE_TTL = 24 * 3600


class GeoPoint(BaseModel):
    name: str
    country: str | None = None
    country_code: str | None = None
    latitude: float
    longitude: float
    timezone: str | None = None
    source: DataSource = DataSource.live


# name -> (display name, country, code, lat, lon, timezone). Approximate city centres.
_CITIES: dict[str, tuple[str, str, str, float, float, str]] = {
    "lahore": ("Lahore", "Pakistan", "PK", 31.55, 74.34, "Asia/Karachi"),
    "karachi": ("Karachi", "Pakistan", "PK", 24.86, 67.01, "Asia/Karachi"),
    "islamabad": ("Islamabad", "Pakistan", "PK", 33.69, 73.05, "Asia/Karachi"),
    "rawalpindi": ("Rawalpindi", "Pakistan", "PK", 33.60, 73.04, "Asia/Karachi"),
    "faisalabad": ("Faisalabad", "Pakistan", "PK", 31.42, 73.08, "Asia/Karachi"),
    "multan": ("Multan", "Pakistan", "PK", 30.20, 71.47, "Asia/Karachi"),
    "peshawar": ("Peshawar", "Pakistan", "PK", 34.01, 71.58, "Asia/Karachi"),
    "bahawalpur": ("Bahawalpur", "Pakistan", "PK", 29.40, 71.68, "Asia/Karachi"),
    "dubai": ("Dubai", "United Arab Emirates", "AE", 25.20, 55.27, "Asia/Dubai"),
    "abu dhabi": ("Abu Dhabi", "United Arab Emirates", "AE", 24.45, 54.38, "Asia/Dubai"),
    "doha": ("Doha", "Qatar", "QA", 25.29, 51.53, "Asia/Qatar"),
    "riyadh": ("Riyadh", "Saudi Arabia", "SA", 24.71, 46.68, "Asia/Riyadh"),
    "jeddah": ("Jeddah", "Saudi Arabia", "SA", 21.54, 39.17, "Asia/Riyadh"),
    "istanbul": ("Istanbul", "Turkey", "TR", 41.01, 28.98, "Europe/Istanbul"),
    "london": ("London", "United Kingdom", "GB", 51.51, -0.13, "Europe/London"),
    "paris": ("Paris", "France", "FR", 48.86, 2.35, "Europe/Paris"),
    "rome": ("Rome", "Italy", "IT", 41.90, 12.50, "Europe/Rome"),
    "madrid": ("Madrid", "Spain", "ES", 40.42, -3.70, "Europe/Madrid"),
    "berlin": ("Berlin", "Germany", "DE", 52.52, 13.40, "Europe/Berlin"),
    "amsterdam": ("Amsterdam", "Netherlands", "NL", 52.37, 4.90, "Europe/Amsterdam"),
    "kuala lumpur": ("Kuala Lumpur", "Malaysia", "MY", 3.14, 101.69, "Asia/Kuala_Lumpur"),
    "bangkok": ("Bangkok", "Thailand", "TH", 13.76, 100.50, "Asia/Bangkok"),
    "singapore": ("Singapore", "Singapore", "SG", 1.35, 103.82, "Asia/Singapore"),
    "tokyo": ("Tokyo", "Japan", "JP", 35.68, 139.69, "Asia/Tokyo"),
    "new york": ("New York", "United States", "US", 40.71, -74.01, "America/New_York"),
    "toronto": ("Toronto", "Canada", "CA", 43.65, -79.38, "America/Toronto"),
    "sydney": ("Sydney", "Australia", "AU", -33.87, 151.21, "Australia/Sydney"),
    "cairo": ("Cairo", "Egypt", "EG", 30.04, 31.24, "Africa/Cairo"),
    "baku": ("Baku", "Azerbaijan", "AZ", 40.41, 49.87, "Asia/Baku"),
    "colombo": ("Colombo", "Sri Lanka", "LK", 6.93, 79.86, "Asia/Colombo"),
    "kathmandu": ("Kathmandu", "Nepal", "NP", 27.72, 85.32, "Asia/Kathmandu"),
    "dhaka": ("Dhaka", "Bangladesh", "BD", 23.81, 90.41, "Asia/Dhaka"),
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def distance_km(a: GeoPoint, b: GeoPoint) -> float:
    return haversine_km(a.latitude, a.longitude, b.latitude, b.longitude)


def _from_table(name: str) -> GeoPoint | None:
    row = _CITIES.get(name.strip().lower())
    if row is None:
        return None
    display, country, code, lat, lon, tz = row
    return GeoPoint(name=display, country=country, country_code=code, latitude=lat,
                    longitude=lon, timezone=tz, source=DataSource.mock)


async def _geocode_uncached(query: str) -> GeoPoint | None:
    parts = [p.strip() for p in query.split(",") if p.strip()]
    if not parts:
        return None
    name_part, hint = parts[0], " ".join(parts[1:]).lower()
    try:
        data = await fetch_json(
            GEOCODE_URL, {"name": name_part, "count": 5, "language": "en", "format": "json"}
        )
    except ProviderError:
        fallback = _from_table(name_part)
        if fallback is None:
            raise  # provider is down and we don't know this city
        return fallback

    results = data.get("results") or []
    if not results:
        return None  # the provider answered: no such place
    pick = results[0]
    if hint:
        for r in results:
            haystack = f"{r.get('country', '')} {r.get('admin1', '')} {r.get('country_code', '')}".lower()
            if hint in haystack:
                pick = r
                break
    return GeoPoint(
        name=pick.get("name", name_part),
        country=pick.get("country"),
        country_code=pick.get("country_code"),
        latitude=pick["latitude"],
        longitude=pick["longitude"],
        timezone=pick.get("timezone"),
        source=DataSource.live,
    )


async def geocode(query: str) -> GeoPoint | None:
    """City name -> GeoPoint. None = place not found. Raises ProviderError if the
    provider is down and the city is not in the fallback table."""
    return await cache.get_or_set(
        make_key("geocode", query), GEOCODE_TTL, lambda: _geocode_uncached(query)
    )
