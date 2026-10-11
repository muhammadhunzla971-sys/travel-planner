from datetime import date, timedelta

import pytest

from app.config import get_settings
from app.models import TripRequest
from app.tools.cache import cache


def make_request(**overrides) -> TripRequest:
    start = date.today() + timedelta(days=30)
    data = {
        "budget": 2000,
        "currency": "usd",
        "origin": "Lahore",
        "destination": "Istanbul",
        "start_date": start,
        "end_date": start + timedelta(days=5),
        "travelers": 2,
    }
    data.update(overrides)
    return TripRequest(**data)


@pytest.fixture
def request_obj() -> TripRequest:
    return make_request()


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """Tests must never call the real Groq API, even if a key exists on this machine."""
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("LLM_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_real_restaurant_lookup(monkeypatch):
    """Restaurant data comes from Overpass; tests must not hit it (override with patch_all)."""
    from app.tools.http import ProviderError

    async def down(url, params=None, **kw):
        raise ProviderError("overpass blocked in tests")

    monkeypatch.setattr("app.tools.restaurants.fetch_json", down)
    yield
