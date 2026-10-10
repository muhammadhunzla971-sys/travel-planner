"""Builders for agent tests (no network, no LLM)."""
from app.agents import AgentContext
from app.models.plan import DataSource
from app.services.budget import allocate_budget
from app.services.trip_data import TripData
from app.tools.flights import search_flights
from app.tools.hotels import search_stays
from app.tools.places import Place
from tests.conftest import make_request
from tests.fakes import ISTANBUL, LAHORE, USD_TO_USD


def place(name, category="sightseeing", popularity=1000, fee=0.0, lat=41.01, lon=28.98,
          source=DataSource.live) -> Place:
    return Place(name=name, category=category, popularity=popularity, est_entry_usd=fee,
                 latitude=lat, longitude=lon, distance_km=1.0, source=source)


def default_places() -> list[Place]:
    return [
        place("Grand Museum", "museum", 90000, fee=10),
        place("Old Fort", "historic", 80000, fee=8),
        place("Blue Mosque", "religious", 70000),
        place("City Park", "nature", 60000),
        place("Spice Bazaar", "landmark", 50000),
        place("Clock Tower", "sightseeing", 40000),
        place("Art Gallery", "museum", 30000, fee=6),
        place("River Walk", "nature", 20000),
    ]


async def make_ctx(*, attractions=None, weather=None, flights=None, stays=None, fx=USD_TO_USD,
                   food=300.0, **request_overrides) -> AgentContext:
    request = make_request(**request_overrides)
    flights = flights if flights is not None else await search_flights(request, LAHORE, ISTANBUL, fx)
    stays = stays if stays is not None else await search_stays(request, ISTANBUL, fx)
    data = TripData(
        destination=ISTANBUL, origin=LAHORE, fx=fx, cost_level="medium",
        allocation=allocate_budget(request, "medium"), weather=weather or [], weather_summary="",
        attractions=default_places() if attractions is None else attractions,
        flights=flights, stays=stays, food_transport_estimate=food, sources={}, warnings=[])
    return AgentContext(request=request, data=data)


def fake_llm(answer=None, error=None, calls=None):
    """Replacement for chat_json used by monkeypatch."""
    async def _fake(system, user, **kwargs):
        if calls is not None:
            calls.append((system, user))
        if error is not None:
            raise error
        return answer
    return _fake
