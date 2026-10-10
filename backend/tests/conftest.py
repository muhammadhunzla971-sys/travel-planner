from datetime import date, timedelta

import pytest

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
