"""Things to see near the destination.

Live provider: Wikipedia (free, no key), in three small steps:
  1. geosearch  - up to 500 geotagged pages within 10 km of the city centre
  2. category   - "Category:Tourist attractions in <city>" (curated by editors; may not exist)
  3. details    - short description + page views (last 30 days) for up to 300 candidates,
                  in batches of 50 titles
Ranking = popularity (page views) + curated-category bonus + a little for category/closeness,
so Hagia Sophia beats an obscure chapel that merely sits closer to the centre point.

Entry fees are NOT in Wikipedia, so they are estimated by category (and labelled so).
If Wikipedia is down, a few generic, clearly-labelled activities are returned instead.
"""
import asyncio
import math
import re
from typing import Any

from pydantic import BaseModel

from app.models.plan import DataSource
from app.tools.cache import cache, make_key
from app.tools.geo import GeoPoint, haversine_km
from app.tools.http import ProviderError, fetch_json

WIKI_URL = "https://en.wikipedia.org/w/api.php"
PLACES_TTL = 24 * 3600
GEO_RADIUS_M = 10_000
GEO_LIMIT = 500
CATEGORY_LIMIT = 200
MAX_CANDIDATES = 300
BATCH = 50
DEFAULT_LIMIT = 30

# page titles with these WORDS are usually not visitor attractions
_SKIP_WORDS = ("school", "college", "university", "hospital", "airport", "station", "district",
               "neighbourhood", "neighborhood", "municipality", "province", "railway", "metro",
               "highway", "road", "street", "avenue", "stadium", "cemetery", "company", "bank",
               "battle", "siege", "fall", "treaty", "line", "tunnel", "ministry", "embassy")
_SKIP_RE = re.compile(r"\b(?:" + "|".join(_SKIP_WORDS) + r")\b", re.IGNORECASE)

# if the short description says this, the page is an area / person / event, not a sight
_NOT_A_SIGHT = ("neighbourhood", "neighborhood", "district", "municipality", "suburb", "village",
                "city in", "town in", "province", "capital", "metropolitan", "urban area",
                "commune", "county", "borough", "footballer", "politician", "actor", "singer",
                "album", "film", "television", "newspaper", "football club", "sports club",
                "company", "university", "school", "hospital", "railway", "metro station",
                "born ", "battle", "siege")

_CATEGORY_WORDS = [
    ("museum", ("museum", "gallery", "exhibition")),
    ("historic", ("palace", "castle", "fort", "tower", "citadel", "ruins", "tomb", "aqueduct",
                  "cistern", "walls", "fortress")),
    ("religious", ("mosque", "church", "cathedral", "temple", "shrine", "synagogue", "basilica",
                   "chapel", "monastery")),
    ("nature", ("park", "garden", "lake", "beach", "mountain", "island", "waterfall", "forest")),
    ("landmark", ("bridge", "square", "gate", "monument", "market", "bazaar", "fountain")),
]
# popularity dominates (3 points per factor of 10 in page views); the category only nudges
_CATEGORY_BONUS = {"museum": 0.8, "historic": 0.8, "landmark": 0.6, "nature": 0.6,
                   "religious": 0.4, "sightseeing": 0.0}
CURATED_BONUS = 2.5  # listed in "Tourist attractions in <city>"

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
    curated: bool = False          # listed in the city's "Tourist attractions" category
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


def _rank_score(place: Place) -> float:
    views = place.popularity or 0
    return (3.0 * math.log10(views + 10) + _CATEGORY_BONUS.get(place.category, 0.0)
            + (CURATED_BONUS if place.curated else 0.0) - 0.05 * (place.distance_km or 0.0))


# ---- Wikipedia calls --------------------------------------------------------
_BASE = {"action": "query", "format": "json", "formatversion": 2}


async def _geosearch(dest: GeoPoint) -> list[dict[str, Any]]:
    data = await fetch_json(WIKI_URL, {
        **_BASE, "list": "geosearch", "gscoord": f"{dest.latitude}|{dest.longitude}",
        "gsradius": GEO_RADIUS_M, "gslimit": GEO_LIMIT, "gsnamespace": 0})
    rows = ((data or {}).get("query") or {}).get("geosearch") or []
    return [r for r in rows if isinstance(r, dict) and r.get("title")]


async def _category_titles(dest: GeoPoint) -> list[str]:
    data = await fetch_json(WIKI_URL, {
        **_BASE, "list": "categorymembers", "cmtitle": f"Category:Tourist attractions in {dest.name}",
        "cmnamespace": 0, "cmlimit": CATEGORY_LIMIT})
    rows = ((data or {}).get("query") or {}).get("categorymembers") or []
    return [r["title"] for r in rows if isinstance(r, dict) and r.get("title")]


async def _details_batch(titles: list[str]) -> dict[str, dict[str, Any]]:
    data = await fetch_json(WIKI_URL, {
        **_BASE, "titles": "|".join(titles), "redirects": 1,
        "prop": "pageviews|description|coordinates", "pvipdays": 30, "pvilimit": "max",
        "colimit": "max"})
    out: dict[str, dict[str, Any]] = {}
    for page in ((data or {}).get("query") or {}).get("pages") or []:
        if isinstance(page, dict) and page.get("title") and not page.get("missing"):
            out[page["title"]] = page
    return out


def _views(page: dict[str, Any]) -> int | None:
    raw = page.get("pageviews")
    if not isinstance(raw, dict):
        return None
    total = sum(v for v in raw.values() if isinstance(v, int | float))
    return int(total) or None


async def _details(titles: list[str]) -> dict[str, dict[str, Any]]:
    batches = [titles[i:i + BATCH] for i in range(0, len(titles), BATCH)]
    results = await asyncio.gather(*[_details_batch(b) for b in batches], return_exceptions=True)
    merged: dict[str, dict[str, Any]] = {}
    for r in results:
        if isinstance(r, dict):  # a failed batch just means no popularity data for those titles
            merged.update(r)
    return merged


# ---- turning raw pages into ranked places -----------------------------------
def _build_places(dest: GeoPoint, geo: list[dict[str, Any]], cats: list[str],
                  details: dict[str, dict[str, Any]], limit: int) -> list[Place]:
    geo_by_title = {g["title"]: g for g in geo}
    curated = set(cats)
    # curated titles first, then the nearest geosearch results, deduplicated, capped
    titles = list(dict.fromkeys([*cats, *geo_by_title])) [:MAX_CANDIDATES]

    places: list[Place] = []
    for title in titles:
        if title.strip().lower() == dest.name.strip().lower() or _SKIP_RE.search(title):
            continue
        page = details.get(title, {})
        desc = (page.get("description") or "").strip()
        if desc and any(w in desc.lower() for w in _NOT_A_SIGHT):
            continue
        lat = lon = None
        if title in geo_by_title:
            lat, lon = geo_by_title[title].get("lat"), geo_by_title[title].get("lon")
        if lat is None:
            coords = (page.get("coordinates") or [{}])[0]
            lat, lon = coords.get("lat"), coords.get("lon")
        if lat is None or lon is None:
            continue
        category = categorize(f"{title} {desc}") if desc else categorize(title)
        is_curated = title in curated
        if not desc and category == "sightseeing" and not is_curated:
            continue  # nothing tells us this is a sight
        places.append(Place(
            name=title, category=category, description=desc[:200] or None,
            latitude=lat, longitude=lon,
            distance_km=round(haversine_km(dest.latitude, dest.longitude, lat, lon), 1),
            est_entry_usd=_EST_ENTRY_USD.get(category, 0.0), popularity=_views(page),
            curated=is_curated, source=DataSource.live))
    places.sort(key=_rank_score, reverse=True)
    return places[:limit]


async def _find(dest: GeoPoint, limit: int) -> list[Place]:
    geo_res, cat_res = await asyncio.gather(_geosearch(dest), _category_titles(dest),
                                            return_exceptions=True)
    geo = geo_res if isinstance(geo_res, list) else []
    cats = cat_res if isinstance(cat_res, list) else []
    if not geo and not cats:
        if isinstance(geo_res, BaseException):
            raise geo_res if isinstance(geo_res, ProviderError) else ProviderError(str(geo_res))
        return []
    candidates = list(dict.fromkeys([*cats, *(g["title"] for g in geo)]))[:MAX_CANDIDATES]
    details = await _details(candidates)
    return _build_places(dest, geo, cats, details, limit)


async def find_attractions(dest: GeoPoint, limit: int = DEFAULT_LIMIT) -> list[Place]:
    """Live attractions if possible, topped up with generic ones so we always return something."""
    key = make_key("places-v2", dest.name, round(dest.latitude, 2), round(dest.longitude, 2), limit)
    try:
        live = await cache.get_or_set(key, PLACES_TTL, lambda: _find(dest, limit))
    except ProviderError:
        live = []
    live = live or []
    if len(live) >= 5:
        return live
    return live + generic_activities(dest)
