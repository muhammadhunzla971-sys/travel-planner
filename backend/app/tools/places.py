"""Things to see near the destination.

Live provider: Wikipedia geosearch (free, no key) = notable places with a short
description. Entry fees are NOT in Wikipedia, so they are estimated by category.
Fallback: a few generic, clearly-labelled activities.
"""
import math

from pydantic import BaseModel

from app.models.plan import DataSource
from app.tools.cache import cache, make_key
from app.tools.geo import GeoPoint, haversine_km
from app.tools.http import ProviderError, fetch_json

WIKI_URL = "https://en.wikipedia.org/w/api.php"
PLACES_TTL = 24 * 3600

# page titles containing these are usually not visitor attractions
_SKIP = ("school", "college", "university", "hospital", "airport", "station", "district",
         "neighbourhood", "neighborhood", "municipality", "province", "railway", "metro",
         "highway", "road", "street", "avenue", "stadium", "cemetery", "company", "bank")

_CATEGORY_WORDS = [
    ("museum", ("museum", "gallery", "exhibition")),
    ("historic", ("palace", "castle", "fort", "tower", "citadel", "ruins", "tomb")),
    ("religious", ("mosque", "church", "cathedral", "temple", "shrine", "synagogue", "basilica")),
    ("nature", ("park", "garden", "lake", "beach", "mountain", "island", "waterfall", "forest")),
    ("landmark", ("bridge", "square", "gate", "monument", "market", "bazaar", "fountain")),
]
# if the short description says this, the page is a place name / area, not a sight
_NOT_A_SIGHT = ("neighbourhood", "neighborhood", "district", "municipality", "suburb", "village",
                "city in", "town in", "province", "capital", "metropolitan", "urban area",
                "commune", "county", "borough")
# ranking: popular pages first, then more "visit-worthy" categories, then closer ones
_CATEGORY_BONUS = {"museum": 1.5, "historic": 1.5, "landmark": 1.0, "nature": 1.0,
                   "religious": 0.5, "sightseeing": 0.0}

# rough entry fee in USD per person, by category (ESTIMATE)
_EST_ENTRY_USD = {"museum": 12.0, "historic": 10.0, "religious": 0.0, "nature": 0.0,
                  "landmark": 0.0, "sightseeing": 0.0}


class Place(BaseModel):
    name: str
    category: str = "sightseeing"
    description: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    distance_km: float | None = None
    est_entry_usd: float = 0.0
    popularity: int | None = None  # Wikipedia page views, last 30 days (higher = better known)
    source: DataSource = DataSource.live


def categorize(title: str) -> str:
    t = title.lower()
    for category, words in _CATEGORY_WORDS:
        if any(w in t for w in words):
            return category
    return "sightseeing"


def generic_activities(dest: GeoPoint) -> list[Place]:
    city = dest.name
    items = [
        (f"Walk around the centre of {city}", "sightseeing"),
        (f"Visit the main museum in {city}", "museum"),
        (f"Browse a local market in {city}", "landmark"),
        (f"Try local food at a popular restaurant in {city}", "food"),
        (f"Relax in a city park in {city}", "nature"),
    ]
    return [Place(name=n, category=c, est_entry_usd=_EST_ENTRY_USD.get(c, 0.0),
                  description="Generic suggestion (no live place data available).",
                  source=DataSource.estimated) for n, c in items]


def _views(page: dict) -> int:
    raw = page.get("pageviews")
    if not isinstance(raw, dict):
        return 0
    return sum(v for v in raw.values() if isinstance(v, int | float))


def _rank_score(place: Place) -> float:
    views = place.popularity or 0
    return (2.0 * math.log10(views + 10) + _CATEGORY_BONUS.get(place.category, 0.0)
            - 0.05 * (place.distance_km or 0.0))


def _parse(data: dict, dest: GeoPoint, limit: int) -> list[Place]:
    pages = (data.get("query") or {}).get("pages") or []
    places: list[Place] = []
    for page in pages:
        title = page.get("title") or ""
        extract = (page.get("extract") or "").strip()
        short = (page.get("description") or "").strip()
        text = extract or short
        coords = (page.get("coordinates") or [{}])[0]
        lat, lon = coords.get("lat"), coords.get("lon")
        if not title or lat is None or lon is None:
            continue
        if len(text) < (30 if extract else 8):
            continue
        if title.strip().lower() == dest.name.strip().lower():
            continue  # the city itself
        if any(word in title.lower() for word in _SKIP):
            continue
        blurb = (short or extract[:160]).lower()
        if any(word in blurb for word in _NOT_A_SIGHT) or any(w in extract[:120].lower() for w in _NOT_A_SIGHT):
            continue
        category = categorize(title)
        places.append(Place(
            name=title, category=category, description=text[:300],
            latitude=lat, longitude=lon,
            distance_km=round(haversine_km(dest.latitude, dest.longitude, lat, lon), 1),
            est_entry_usd=_EST_ENTRY_USD.get(category, 0.0),
            popularity=_views(page) or None, source=DataSource.live,
        ))
    places.sort(key=_rank_score, reverse=True)
    return places[:limit]


async def _find(dest: GeoPoint, limit: int) -> list[Place]:
    data = await fetch_json(WIKI_URL, {
        "action": "query", "format": "json", "formatversion": 2,
        "generator": "geosearch", "ggscoord": f"{dest.latitude}|{dest.longitude}",
        "ggsradius": 10000, "ggslimit": 50,
        "prop": "extracts|coordinates|pageviews|description", "exintro": 1, "explaintext": 1,
        "exsentences": 2, "exlimit": "max", "colimit": "max",
        "pvipdays": 30, "pvilimit": "max",
    })
    return _parse(data, dest, limit)


async def find_attractions(dest: GeoPoint, limit: int = 15) -> list[Place]:
    """Live attractions if possible, topped up with generic ones so we always return something."""
    key = make_key("places", round(dest.latitude, 2), round(dest.longitude, 2), limit)
    try:
        live = await cache.get_or_set(key, PLACES_TTL, lambda: _find(dest, limit))
    except ProviderError:
        live = []
    live = live or []
    if len(live) >= 5:
        return live
    return live + generic_activities(dest)
