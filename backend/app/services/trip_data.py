"""Gathers everything the agents need about a trip in one go (the "research" step).

Each provider call is wrapped so a failure becomes a warning + fallback data,
never a crash. The orchestrator (Step 5) will call gather_trip_data().
"""
import asyncio
import logging
from collections.abc import Awaitable
from typing import TypeVar

from pydantic import BaseModel

from app.models.allocation import BudgetAllocation
from app.models.plan import FlightOption, StayOption
from app.models.request import TripRequest
from app.services.budget import allocate_budget
from app.tools.cost_index import cost_level, food_transport_usd_per_day
from app.tools.currency import Rate, get_rate
from app.tools.flights import search_flights
from app.tools.geo import GeoPoint, geocode
from app.tools.hotels import search_stays
from app.tools.http import ProviderError
from app.tools.places import Place, find_attractions
from app.tools.weather import DayWeather, get_weather, summarize_weather

log = logging.getLogger(__name__)
T = TypeVar("T")


class DestinationNotFound(Exception):
    """The destination could not be found."""


class DataUnavailable(Exception):
    """A required lookup (destination or currency) is down and has no fallback."""


class TripData(BaseModel):
    destination: GeoPoint
    origin: GeoPoint | None = None
    fx: Rate  # USD -> request currency
    cost_level: str
    allocation: BudgetAllocation
    weather: list[DayWeather]
    weather_summary: str
    attractions: list[Place]
    flights: list[FlightOption]
    stays: list[StayOption]
    food_transport_estimate: float  # whole trip, in the request currency
    sources: dict[str, str]
    warnings: list[str]


async def _safe(coro: Awaitable[T], default: T, label: str, warnings: list[str]) -> T:
    try:
        return await coro
    except ProviderError as exc:
        warnings.append(f"{label} unavailable right now ({exc}); using fallback.")
    except Exception:  # never let one provider crash the whole plan
        log.exception("unexpected error in %s", label)
        warnings.append(f"{label} failed unexpectedly; using fallback.")
    return default


async def gather_trip_data(request: TripRequest) -> TripData:
    warnings: list[str] = []

    try:
        dest = await geocode(request.destination)
    except ProviderError as exc:
        raise DataUnavailable(f"Could not look up the destination right now: {exc}") from exc
    if dest is None:
        raise DestinationNotFound(f"Could not find a place called '{request.destination}'.")

    try:
        fx = await get_rate("USD", request.currency)
    except ProviderError as exc:
        raise DataUnavailable(f"No exchange rate available for {request.currency}: {exc}") from exc

    origin: GeoPoint | None = None
    if request.origin:
        origin = await _safe(geocode(request.origin), None, "Origin lookup", warnings)
        if origin is None and not any("Origin lookup" in w for w in warnings):
            warnings.append(f"Origin '{request.origin}' was not recognised; flights skipped.")
    else:
        warnings.append("No origin city given, so flight options were skipped.")

    weather, attractions, flights, stays = await asyncio.gather(
        _safe(get_weather(dest.latitude, dest.longitude, request.start_date, request.end_date),
              [], "Weather", warnings),
        _safe(find_attractions(dest), [], "Attractions", warnings),
        _safe(search_flights(request, origin, dest, fx), [], "Flights", warnings),
        _safe(search_stays(request, dest, fx), [], "Stays", warnings),
    )

    level = cost_level(dest.country_code)
    food_usd = food_transport_usd_per_day(dest.country_code, request.preferences.style)
    food_total = round(food_usd * request.travelers * request.num_days * fx.rate, 2)

    sources = {
        "destination": dest.source.value,
        "exchange_rate": fx.source.value,
        "weather": weather[0].source.value if weather else "unavailable",
        "attractions": "live" if any(p.source.value == "live" for p in attractions) else "estimated",
        "flights": flights[0].source.value if flights else "unavailable",
        "stays": stays[0].source.value if stays else "unavailable",
    }
    if any(v in ("estimated", "mock") for v in sources.values()):
        warnings.append("Some data is estimated, not live. Check the 'sources' field.")

    return TripData(
        destination=dest, origin=origin, fx=fx, cost_level=level,
        allocation=allocate_budget(request, level),  # type: ignore[arg-type]
        weather=weather, weather_summary=summarize_weather(weather),
        attractions=attractions, flights=flights, stays=stays,
        food_transport_estimate=food_total, sources=sources, warnings=warnings,
    )
