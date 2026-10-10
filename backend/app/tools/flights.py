"""Flight options.

No free, keyless flight-price API exists, so the default provider ESTIMATES
fares from the distance between the two cities (clearly labelled "estimated").
`FlightProvider` is the plug-in point: a real provider (with an API key) can be
added later and selected with the FLIGHT_PROVIDER setting.
"""
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.plan import DataSource, FlightOption
from app.models.request import TripRequest
from app.tools.currency import Rate
from app.tools.geo import GeoPoint, distance_km

CRUISE_KMH = 820.0

# (id, label, depart hour:min, price factor, stops(if long haul), extra minutes on the ground)
_TEMPLATES = [
    ("direct", "direct", time(9, 30), 1.25, 0, 30),
    ("one-stop", "1 stop", time(7, 15), 1.00, 1, 150),
    ("budget-late", "budget, late arrival", time(20, 40), 0.82, 1, 240),
]


class FlightProvider(Protocol):
    async def search(self, request: TripRequest, origin: GeoPoint, dest: GeoPoint,
                     usd_to_quote: Rate) -> list[FlightOption]: ...


def _tz(name: str | None):
    try:
        return ZoneInfo(name) if name else UTC
    except ZoneInfoNotFoundError:
        return UTC


def season_factor(start: date, today: date | None = None) -> float:
    today = today or date.today()
    factor = 1.15 if start.month in (6, 7, 8, 12) else 1.0
    if (start - today).days < 14:
        factor *= 1.2  # last-minute
    return factor


def round_trip_usd_per_person(km: float) -> float:
    return 90.0 + 0.11 * km


class EstimatedFlightProvider:
    async def search(self, request: TripRequest, origin: GeoPoint, dest: GeoPoint,
                     usd_to_quote: Rate) -> list[FlightOption]:
        km = distance_km(origin, dest)
        base_pp = round_trip_usd_per_person(km) * season_factor(request.start_date)
        o_tz, d_tz = _tz(origin.timezone), _tz(dest.timezone)
        options: list[FlightOption] = []
        for key, label, dep_time, factor, long_haul_stops, ground_min in _TEMPLATES:
            stops = long_haul_stops if km >= 1500 else 0
            minutes = int(km / CRUISE_KMH * 60) + 30 + (ground_min if stops else 0)
            out_dep = datetime.combine(request.start_date, dep_time, tzinfo=o_tz)
            out_arr = (out_dep + timedelta(minutes=minutes)).astimezone(d_tz)
            ret_dep = datetime.combine(request.end_date, dep_time, tzinfo=d_tz)
            ret_arr = (ret_dep + timedelta(minutes=minutes)).astimezone(o_tz)
            price = round(base_pp * factor * request.travelers * usd_to_quote.rate, 2)
            options.append(FlightOption(
                id=f"est-{key}", airline=f"Typical airline ({label}, estimate)",
                origin=origin.name, destination=dest.name,
                depart_at=out_dep, arrive_at=out_arr,
                return_depart_at=ret_dep, return_arrive_at=ret_arr,
                stops=stops, duration_minutes=minutes, total_price=price,
                currency=usd_to_quote.quote, booking_url=None, source=DataSource.estimated,
            ))
        options.sort(key=lambda f: f.total_price)
        return options


def get_flight_provider(name: str = "estimated") -> FlightProvider:
    # Future: "amadeus", "serpapi", ... (need API keys). Unknown names fall back safely.
    return EstimatedFlightProvider()


async def search_flights(request: TripRequest, origin: GeoPoint | None, dest: GeoPoint,
                         usd_to_quote: Rate, provider: str = "estimated") -> list[FlightOption]:
    if origin is None:
        return []
    return await get_flight_provider(provider).search(request, origin, dest, usd_to_quote)
