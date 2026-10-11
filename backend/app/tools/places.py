"""Things to see near the destination.

Live provider: Wikipedia (free, no key), in three small steps:
  1. geosearch  - geotagged pages around a grid of ~13 sample points (up to 500 each), so famous
                  places a few km from the centre are not lost in the dense old town
  2. category   - "Category:Tourist attractions in <city>" (curated by editors; may not exist)
  3. details    - short description + page views (last 30 days) for up to 600 candidates,
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
GEO_RADIUS_M = 2_500       # per sample point
GEO_LIMIT = 500            # per sample point
RING_KM = (3.0, 6.0)       # sample rings around the centre
CATEGORY_LIMIT = 200
MAX_CANDIDATES = 600
MIN_VIEWS = 500            # below this (30 days) a page is "obscure" - used only to fill gaps
MIN_GOOD_PLACES = 8
BATCH = 50
DEFAULT_LIMIT = 30

# page titles with these WORDS are usually not visitor attractions
_SKIP_WORDS = ("school", "college", "university", "hospital", "airport", "station", "district",
               "neighbourhood", "neighborhood", "municipality", "province", "railway", "metro",
               "highway", "road", "street", "avenue", "stadium", "cemetery", "company", "bank",
               "battle", "siege", "fall", "treaty", "line", "tunnel", "ministry", "embassy")
_EVENT_WORDS = ("earthquake", "massacre", "bombing", "bombings", "fire", "riot", "riots", "attack",
                "coup", "protest", "protests", "revolt", "uprising", "assassination", "shooting",
                "flood", "plague", "pogrom", "incident", "crisis", "election", "census", "strike",
                "history of", "list of", "timeline", "conquest", "occupation")
_SKIP_RE = re.compile(r"\b(?:" + "|".join((*_SKIP_WORDS, *_EVENT_WORDS)) + r")\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d{3,4}\b")  # "1999 Izmit earthquake", "1766 ..." - events, not sights

# if the short description says this, the page is an area / person / event, not a sight
_NOT_A_SIGHT = ("neighbourhood", "neighborhood", "district", "municipality", "suburb", "village",
                "city in", "town in", "province", "capital", "metropolitan", "urban area",
                "commune", "county", "borough", "footballer", "politician", "actor", "singer",
                "album", "film", "television", "newspaper", "football club", "sports club",
                "company", "university", "school", "hospital", "railway", "metro station",
                "born ", "battle", "siege", "earthquake", "massacre", "terrorist", "bombing",
                "attack", "riot", "protest", "uprising", "historical period", "treaty")

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


def _title_ok(title: str, dest: GeoPoint) -> bool:
    if title.strip().lower() == dest.name.strip().lower():
        return False
    return not (_SKIP_RE.search(title) or _NUMBER_RE.search(title))


def _sample_points(dest: GeoPoint) -> list[tuple[float, float]]:
    """Centre + 8 points on a 3 km ring + 4 points on a 6 km ring (13 total)."""
    pts = [(dest.latitude, dest.longitude)]
    km_lat = 111.0
    km_lon = max(111.0 * math.cos(math.radians(dest.latitude)), 1.0)
    for ring, n in zip(RING_KM, (8, 4), strict=True):
        for k in range(n):
            ang = 2 * math.pi * k / n
            pts.append((round(dest.latitude + ring * math.cos(ang) / km_lat, 5),
                        round(dest.longitude + ring * math.sin(ang) / km_lon, 5)))
    return pts


def _rank_score(place: Place) -> float:
    views = place.popularity or 0
    return (3.0 * math.log10(views + 10) + _CATEGORY_BONUS.get(place.category, 0.0)
            + (CURATED_BONUS if place.curated else 0.0) - 0.05 * (place.distance_km or 0.0))


# ---- Wikipedia calls --------------------------------------------------------
_BASE = {"action": "query", "format": "json", "formatversion": 2}
_MAX_PARALLEL = 4  # Wikipedia answers 429 if we fire ~25 requests at once
_sem: asyncio.Semaphore | None = None


async def _wiki(params: dict[str, Any]) -> Any:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(_MAX_PARALLEL)
    async with _sem:
        return await fetch_json(WIKI_URL, params)


async def _geosearch_point(lat: float, lon: float) -> list[dict[str, Any]]:
    data = await _wiki({
        **_BASE, "list": "geosearch", "gscoord": f"{lat}|{lon}",
        "gsradius": GEO_RADIUS_M, "gslimit": GEO_LIMIT, "gsnamespace": 0})
    rows = ((data or {}).get("query") or {}).get("geosearch") or []
    return [r for r in rows if isinstance(r, dict) and r.get("title")]


async def _geosearch(dest: GeoPoint) -> list[dict[str, Any]]:
    """Search around several points and merge. Fails only if EVERY point fails."""
    results = await asyncio.gather(*[_geosearch_point(la, lo) for la, lo in _sample_points(dest)],
                                   return_exceptions=True)
    merged: dict[str, dict[str, Any]] = {}
    for r in results:
        if isinstance(r, list):
            for row in r:
                merged.setdefault(row["title"], row)
    if not merged:
        errors = [r for r in results if isinstance(r, BaseException)]
        if errors:
            raise errors[0] if isinstance(errors[0], ProviderError) else ProviderError(str(errors[0]))
    return list(merged.values())


async def _category_titles(dest: GeoPoint) -> list[str]:
    data = await _wiki({
        **_BASE, "list": "categorymembers", "cmtitle": f"Category:Tourist attractions in {dest.name}",
        "cmnamespace": 0, "cmlimit": CATEGORY_LIMIT})
    rows = ((data or {}).get("query") or {}).get("categorymembers") or []
    return [r["title"] for r in rows if isinstance(r, dict) and r.get("title")]


async def _details_batch(titles: list[str]) -> dict[str, dict[str, Any]]:
    data = await _wiki({
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


def _reject_reason(title: str, page: dict[str, Any], dest: GeoPoint, has_coords: bool,
                   is_curated: bool) -> str | None:
    if not _title_ok(title, dest):
        return "title_filter"
    desc = (page.get("description") or "").strip()
    if desc and any(w in desc.lower() for w in _NOT_A_SIGHT):
        return "description_filter"
    if not has_coords:
        return "no_coordinates"
    category = categorize(f"{title} {desc}") if desc else categorize(title)
    if not desc and category == "sightseeing" and not is_curated:
        return "no_description_and_unrecognised_title"
    return None


async def diagnose(dest: GeoPoint, check: tuple[str, ...] = ("Hagia Sophia", "Blue Mosque",
                                                              "Topkapı Palace", "Galata Tower")) -> dict[str, Any]:
    """Step-by-step report of what Wikipedia returned and why places were kept or dropped."""
    pts = _sample_points(dest)
    geo_res = await asyncio.gather(*[_geosearch_point(la, lo) for la, lo in pts], return_exceptions=True)
    geo: dict[str, dict[str, Any]] = {}
    geo_errors: list[str] = []
    for r in geo_res:
        if isinstance(r, list):
            for row in r:
                geo.setdefault(row["title"], row)
        else:
            geo_errors.append(str(r)[:120])
    try:
        cats = await _category_titles(dest)
        cat_error = None
    except Exception as exc:  # noqa: BLE001 - diagnostics only
        cats, cat_error = [], str(exc)[:120]
    ordered = [*cats, *geo]
    candidates = [t for t in dict.fromkeys(ordered) if _title_ok(t, dest)][:MAX_CANDIDATES]
    batches = [candidates[i:i + BATCH] for i in range(0, len(candidates), BATCH)]
    det_res = await asyncio.gather(*[_details_batch(b) for b in batches], return_exceptions=True)
    details: dict[str, dict[str, Any]] = {}
    det_errors: list[str] = []
    for r in det_res:
        if isinstance(r, dict):
            details.update(r)
        else:
            det_errors.append(str(r)[:120])
    reasons: dict[str, int] = {}
    for t in dict.fromkeys(ordered):
        page = details.get(t, {})
        has_coords = t in geo or bool(page.get("coordinates"))
        why = _reject_reason(t, page, dest, has_coords, t in set(cats)) if t in candidates \
            else "title_filter"
        if why:
            reasons[why] = reasons.get(why, 0) + 1
    ranked = await _find(dest, 25)
    names_lower = {t.lower(): t for t in dict.fromkeys(ordered)}
    checks = {}
    for name in check:
        real = names_lower.get(name.lower())
        page = details.get(real, {}) if real else {}
        checks[name] = {
            "found_in_geosearch_or_category": bool(real), "in_candidates": bool(real in candidates),
            "details_fetched": bool(page), "views_30d": _views(page) if page else None,
            "description": page.get("description"),
            "rejected_because": (_reject_reason(real, page, dest, real in geo or bool(page.get("coordinates")),
                                                real in set(cats)) if real else "not_returned_by_wikipedia")}
    return {
        "centre": [dest.latitude, dest.longitude],
        "geosearch": {"points": len(pts), "points_failed": len(geo_errors), "errors": geo_errors[:3],
                      "unique_titles": len(geo)},
        "category": {"titles": len(cats), "error": cat_error},
        "candidates": len(candidates),
        "details": {"batches": len(batches), "batches_failed": len(det_errors), "errors": det_errors[:3],
                    "pages_returned": len(details),
                    "with_views": sum(1 for p in details.values() if _views(p))},
        "rejected_by_reason": reasons,
        "checks": checks,
        "top": [{"name": p.name, "views": p.popularity, "km": p.distance_km, "curated": p.curated,
                 "category": p.category} for p in ranked],
    }


# ---- turning raw pages into ranked places -----------------------------------
def _build_places(dest: GeoPoint, geo: list[dict[str, Any]], cats: list[str],
                  details: dict[str, dict[str, Any]], limit: int) -> list[Place]:
    geo_by_title = {g["title"]: g for g in geo}
    curated = set(cats)
    # curated titles first, then the nearest geosearch results, deduplicated, capped
    titles = list(dict.fromkeys([*cats, *geo_by_title]))[:MAX_CANDIDATES]

    places: list[Place] = []
    for title in titles:
        if not _title_ok(title, dest):
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
    # prefer fewer, better places: drop obscure pages unless that would leave too few
    good = [p for p in places if p.curated or (p.popularity or 0) >= MIN_VIEWS]
    if len(good) < MIN_GOOD_PLACES:
        good = places[:max(MIN_GOOD_PLACES, len(good))]
    return good[:limit]


async def _find(dest: GeoPoint, limit: int) -> list[Place]:
    geo_res, cat_res = await asyncio.gather(_geosearch(dest), _category_titles(dest),
                                            return_exceptions=True)
    geo = geo_res if isinstance(geo_res, list) else []
    cats = cat_res if isinstance(cat_res, list) else []
    if not geo and not cats:
        if isinstance(geo_res, BaseException):
            raise geo_res if isinstance(geo_res, ProviderError) else ProviderError(str(geo_res))
        return []
    ordered = [*cats, *(g["title"] for g in geo)]
    candidates = [t for t in dict.fromkeys(ordered) if _title_ok(t, dest)][:MAX_CANDIDATES]
    details = await _details(candidates)
    return _build_places(dest, geo, cats, details, limit)


async def find_attractions(dest: GeoPoint, limit: int = DEFAULT_LIMIT) -> list[Place]:
    """Live attractions if possible, topped up with generic ones so we always return something."""
    key = make_key("places-v3", dest.name, round(dest.latitude, 2), round(dest.longitude, 2), limit)
    try:
        live = await cache.get_or_set(key, PLACES_TTL, lambda: _find(dest, limit))
    except ProviderError:
        live = []
    live = live or []
    if len(live) >= 5:
        return live
    return live + generic_activities(dest)
