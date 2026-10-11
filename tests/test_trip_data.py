from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.trip_data import (
    DataUnavailable,
    DestinationNotFound,
    gather_trip_data,
)
from tests.conftest import make_request
from tests.fakes import (
    ER_API,
    FORECAST,
    GEOCODE_ISTANBUL,
    GEOCODE_LAHORE,
    WIKI_ISTANBUL,
    all_down,
    make_fetch,
    patch_all,
)


def _router(destination_payload):
    """Fake geocoder that answers by the requested name."""
    async def geocode_answer(url, params=None, **kw):
        name = (params or {}).get("name", "").lower()
        return destination_payload.get(name, {"generationtime_ms": 1})
    return geocode_answer


async def test_everything_live(monkeypatch):
    geocoder = _router({"istanbul": GEOCODE_ISTANBUL, "lahore": GEOCODE_LAHORE})
    other = make_fetch({"er-api": ER_API, "wikipedia": WIKI_ISTANBUL, "open-meteo.com/v1": FORECAST,
                        "archive-api": FORECAST})

    async def fake(url, params=None, **kw):
        return await (geocoder if "geocoding-api" in url else other)(url, params, **kw)

    for target in ("app.tools.geo", "app.tools.currency", "app.tools.weather", "app.tools.places"):
        monkeypatch.setattr(f"{target}.fetch_json", fake)

    req = make_request(currency="PKR")
    data = await gather_trip_data(req)
    assert data.destination.name == "Istanbul" and data.origin.name == "Lahore"
    assert data.fx.quote == "PKR" and data.fx.rate == 280.0
    assert data.sources["destination"] == "live" and data.sources["exchange_rate"] == "live"
    assert data.sources["attractions"] == "live"
    assert data.sources["flights"] == "estimated" and data.sources["stays"] == "estimated"
    assert len(data.flights) == 3 and len(data.stays) == 4
    assert data.allocation.total == req.budget
    assert data.cost_level == "medium"  # Turkey
    assert data.food_transport_estimate > 0
    assert any("estimated" in w for w in data.warnings)


async def test_survives_total_outage_with_fallbacks(monkeypatch):
    all_down(monkeypatch)
    data = await gather_trip_data(make_request(currency="PKR"))
    assert data.destination.source.value == "mock"
    assert data.fx.source.value == "estimated"
    assert data.weather == [] and data.weather_summary == "Weather data not available."
    assert data.sources["weather"] == "unavailable"
    assert len(data.attractions) >= 5 and data.sources["attractions"] == "estimated"
    assert len(data.flights) == 3 and len(data.stays) == 4
    assert any("Weather" in w for w in data.warnings)


async def test_no_origin_skips_flights(monkeypatch):
    all_down(monkeypatch)
    data = await gather_trip_data(make_request(origin=None))
    assert data.flights == [] and data.sources["flights"] == "unavailable"
    assert any("No origin" in w for w in data.warnings)


async def test_unknown_destination(monkeypatch):
    patch_all(monkeypatch, {"geocoding-api": {"generationtime_ms": 1}, "er-api": ER_API})
    with pytest.raises(DestinationNotFound):
        await gather_trip_data(make_request(destination="Atlantis"))


async def test_destination_lookup_down_and_not_in_fallback(monkeypatch):
    all_down(monkeypatch)
    with pytest.raises(DataUnavailable):
        await gather_trip_data(make_request(destination="Zzyzx Springs"))


async def test_unsupported_currency(monkeypatch):
    patch_all(monkeypatch, {"geocoding-api": GEOCODE_ISTANBUL, "er-api": ER_API})
    with pytest.raises(DataUnavailable):
        await gather_trip_data(make_request(currency="XYZ", origin=None))


# ---- HTTP endpoint -------------------------------------------------------
def _body(**overrides):
    start = date.today() + timedelta(days=30)
    body = {"budget": 2000, "currency": "USD", "origin": "Lahore", "destination": "Istanbul",
            "start_date": start.isoformat(), "end_date": (start + timedelta(days=5)).isoformat(),
            "travelers": 2}
    body.update(overrides)
    return body


def test_tools_preview_endpoint_works_even_when_providers_are_down(monkeypatch):
    all_down(monkeypatch)
    client = TestClient(app)
    r = client.post("/api/tools/preview", json=_body())
    assert r.status_code == 200
    data = r.json()
    assert data["destination"]["name"] == "Istanbul"
    assert set(data["sources"]) == {"destination", "exchange_rate", "weather", "attractions",
                                    "flights", "stays"}
    assert len(data["flights"]) == 3 and data["warnings"]


def test_tools_preview_endpoint_error_codes(monkeypatch):
    client = TestClient(app)
    patch_all(monkeypatch, {"geocoding-api": {"generationtime_ms": 1}, "er-api": ER_API})
    assert client.post("/api/tools/preview", json=_body(destination="Atlantis")).status_code == 422
    all_down(monkeypatch)
    assert client.post("/api/tools/preview",
                       json=_body(destination="Zzyzx Springs")).status_code == 503
