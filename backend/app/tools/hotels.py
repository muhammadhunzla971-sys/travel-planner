"""Stay options.

Like flights, there is no free keyless hotel-price API, so the default provider
ESTIMATES nightly prices from a per-country price level. Names are generic on
purpose (we never invent real hotel names or ratings). A real provider can be
plugged in later behind `StayProvider`.
"""
import math
from typing import Protocol

from app.models.plan import DataSource, StayOption
from app.models.request import TripRequest
from app.tools.cost_index import HOTEL_TIERS, price_multiplier
from app.tools.currency import Rate
from app.tools.geo import GeoPoint


class StayProvider(Protocol):
    async def search(self, request: TripRequest, dest: GeoPoint,
                     usd_to_quote: Rate) -> list[StayOption]: ...


class EstimatedStayProvider:
    async def search(self, request: TripRequest, dest: GeoPoint,
                     usd_to_quote: Rate) -> list[StayOption]:
        mult = price_multiplier(dest.country_code)
        rooms = math.ceil(request.travelers / 2)
        min_stars = request.preferences.min_hotel_stars or 1
        options: list[StayOption] = []
        for tier in HOTEL_TIERS:
            if tier["stars"] < min_stars:
                continue
            units = request.travelers if tier["kind"] == "hostel" else rooms  # beds vs rooms
            nightly = round(tier["base_usd"] * mult * units * usd_to_quote.rate, 2)
            options.append(StayOption(
                id=f"est-{tier['key']}",
                name=f"{tier['label']} in {dest.name} (estimate)",
                kind=tier["kind"], area="City centre (assumed)", rating=None,
                price_per_night=nightly, nights=request.nights,
                total_price=round(nightly * request.nights, 2),
                currency=usd_to_quote.quote, amenities=list(tier["amenities"]),
                booking_url=None, source=DataSource.estimated,
            ))
        options.sort(key=lambda s: s.total_price)
        return options


def get_stay_provider(name: str = "estimated") -> StayProvider:
    return EstimatedStayProvider()


async def search_stays(request: TripRequest, dest: GeoPoint, usd_to_quote: Rate,
                       provider: str = "estimated") -> list[StayOption]:
    return await get_stay_provider(provider).search(request, dest, usd_to_quote)
