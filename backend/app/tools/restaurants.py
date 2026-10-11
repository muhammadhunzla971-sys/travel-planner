"""Places to eat near the destination.

Live provider: OpenStreetMap via the Overpass API (free, no key). OSM has no ratings or prices,
so places are ranked by how well-documented they are (cuisine, website, Wikipedia/Wikidata tags)
and dietary tags (diet:halal, diet:vegetarian, ...) are used when the traveller has dietary needs.
If Overpass is down the list is simply empty and the plan has no meal suggestions.
"""
from typing import Any

from pydantic import BaseModel, Field

from app.models.plan import DataSource
from app.tools.cache import cache, make_key
from app.tools.geo import GeoPoint, haversine_km
from app.tools.http import fetch_json

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
RESTAURANT_TTL = 24 * 3600
RADIUS_M = 4_000
MAX_RESULTS = 120

# traveller wording -> OSM tags that confirm it
_DIET_TAGS = {
    "halal": ("diet:halal",),
    "vegetarian": ("diet:vegetarian", "diet:vegan"),
    "vegan": ("diet:vegan",),
    "kosher": ("diet:kosher",),
    "gluten": ("diet:gluten_free",),
}


class Restaurant(BaseModel):
    name: str
    cuisine: str | None = None
    latitude: float
    longitude: float
    distance_km: float | None = None
    diets: list[str] = Field(default_factory=list)  # confirmed in OSM, e.g. ["halal"]
    website: str | None = None
    quality: float = 0.0
    source: DataSource = DataSource.live


def diet_keys(needs: list[str]) -> list[str]:
    """Normalise free text like 'Halal food' / 'gluten-free' to our keys."""
    found = []
    for need in needs:
        low = need.lower()
        for key in _DIET_TAGS:
            if key in low and key not in found:
                found.append(key)
    return found


def _confirmed_diets(tags: dict[str, Any]) -> list[str]:
    out = []
    for key, osm_tags in _DIET_TAGS.items():
        if any(str(tags.get(t, "")).lower() in ("yes", "only") for t in osm_tags):
            out.append(key)
    return out


def _quality(tags: dict[str, Any]) -> float:
    q = 0.0
    q += 1.0 if tags.get("cuisine") else 0.0
    q += 0.7 if tags.get("website") or tags.get("contact:website") else 0.0
    q += 0.5 if tags.get("opening_hours") else 0.0
    q += 1.5 if tags.get("wikidata") or tags.get("wikipedia") else 0.0
    q += 0.5 if tags.get("phone") or tags.get("contact:phone") else 0.0
    return q


def parse_overpass(dest: GeoPoint, data: Any) -> list[Restaurant]:
    out: list[Restaurant] = []
    seen: set[str] = set()
    for el in (data or {}).get("elements") or []:
        if not isinstance(el, dict):
            continue
        tags = el.get("tags") or {}
        name = str(tags.get("name") or "").strip()
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        if not name or lat is None or lon is None or name.lower() in seen:
            continue
        seen.add(name.lower())
        cuisine = str(tags.get("cuisine") or "").replace(";", ", ").replace("_", " ").strip() or None
        out.append(Restaurant(
            name=name[:80], cuisine=cuisine[:60] if cuisine else None, latitude=float(lat),
            longitude=float(lon), distance_km=round(haversine_km(dest.latitude, dest.longitude, lat, lon), 1),
            diets=_confirmed_diets(tags), website=(tags.get("website") or tags.get("contact:website")),
            quality=_quality(tags)))
    out.sort(key=lambda r: (-r.quality, r.distance_km or 0.0))
    return out[:MAX_RESULTS]


async def _find(dest: GeoPoint) -> list[Restaurant]:
    query = (f'[out:json][timeout:15];nwr["amenity"="restaurant"]["name"]'
             f"(around:{RADIUS_M},{dest.latitude},{dest.longitude});out center 400;")
    data = await fetch_json(OVERPASS_URL, {"data": query}, timeout=14.0, retries=1, backoff=1.0)
    return parse_overpass(dest, data)


async def find_restaurants(dest: GeoPoint) -> list[Restaurant]:
    key = make_key("restaurants-v1", dest.name, round(dest.latitude, 2), round(dest.longitude, 2))
    return await cache.get_or_set(key, RESTAURANT_TTL, lambda: _find(dest))


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    return haversine_km(a[0], a[1], b[0], b[1])


__all__ = ["Restaurant", "diet_keys", "find_restaurants", "km_between", "parse_overpass"]
