import pytest

from app.models.plan import DataSource
from app.tools.currency import convert, get_rate
from app.tools.geo import distance_km, geocode
from app.tools.http import ProviderError
from tests.fakes import (
    ER_API,
    GEOCODE_ISTANBUL,
    ISTANBUL,
    LAHORE,
    all_down,
    patch_all,
)


# ---- geocoding -----------------------------------------------------------
async def test_geocode_live(monkeypatch):
    patch_all(monkeypatch, {"geocoding-api": GEOCODE_ISTANBUL})
    p = await geocode("Istanbul")
    assert p.name == "Istanbul" and p.country_code == "TR"
    assert p.source == DataSource.live
    assert p.timezone == "Europe/Istanbul"


async def test_geocode_uses_country_hint(monkeypatch):
    data = {"results": [
        {"name": "Paris", "country": "United States", "country_code": "US", "admin1": "Texas",
         "latitude": 33.66, "longitude": -95.55, "timezone": "America/Chicago"},
        {"name": "Paris", "country": "France", "country_code": "FR", "admin1": "Ile-de-France",
         "latitude": 48.85, "longitude": 2.35, "timezone": "Europe/Paris"},
    ]}
    patch_all(monkeypatch, {"geocoding-api": data})
    assert (await geocode("Paris, France")).country_code == "FR"
    assert (await geocode("Paris")).country_code == "US"  # no hint = first result


async def test_geocode_not_found_returns_none(monkeypatch):
    patch_all(monkeypatch, {"geocoding-api": {"generationtime_ms": 1.0}})
    assert await geocode("Atlantis") is None


async def test_geocode_falls_back_to_table_when_api_down(monkeypatch):
    all_down(monkeypatch)
    p = await geocode("lahore")
    assert p.country_code == "PK" and p.source == DataSource.mock


async def test_geocode_unknown_city_and_api_down_raises(monkeypatch):
    all_down(monkeypatch)
    with pytest.raises(ProviderError):
        await geocode("Zzyzx Springs")


async def test_geocode_is_cached(monkeypatch):
    calls = []
    patch_all(monkeypatch, {"geocoding-api": GEOCODE_ISTANBUL}, calls)
    await geocode("Istanbul")
    await geocode("istanbul ")
    assert len(calls) == 1


def test_distance_lahore_istanbul_is_plausible():
    km = distance_km(LAHORE, ISTANBUL)
    assert 4000 < km < 4700


# ---- currency ------------------------------------------------------------
async def test_rate_live_cross_rate(monkeypatch):
    patch_all(monkeypatch, {"er-api": ER_API})
    usd_pkr = await get_rate("USD", "PKR")
    assert usd_pkr.rate == 280.0 and usd_pkr.source == DataSource.live
    eur_pkr = await get_rate("EUR", "PKR")
    assert eur_pkr.rate == pytest.approx(280.0 / 0.9)


async def test_rate_second_provider_when_first_fails(monkeypatch):
    patch_all(monkeypatch, {"frankfurter": {"rates": {"EUR": 0.9, "TRY": 40.0}}})
    r = await get_rate("USD", "EUR")
    assert r.provider == "frankfurter" and r.source == DataSource.live


async def test_rate_static_fallback_is_labelled_estimated(monkeypatch):
    all_down(monkeypatch)
    r = await get_rate("USD", "PKR")
    assert r.source == DataSource.estimated
    assert r.rate > 100


async def test_rate_same_currency_and_unknown_currency(monkeypatch):
    all_down(monkeypatch)
    assert (await get_rate("pkr", "PKR")).rate == 1.0
    with pytest.raises(ProviderError):
        await get_rate("USD", "XYZ")


async def test_convert(monkeypatch):
    patch_all(monkeypatch, {"er-api": ER_API})
    amount, rate = await convert(10, "USD", "PKR")
    assert amount == 2800.0 and rate.quote == "PKR"


async def test_rates_are_cached(monkeypatch):
    calls = []
    patch_all(monkeypatch, {"er-api": ER_API}, calls)
    await get_rate("USD", "PKR")
    await get_rate("USD", "EUR")
    assert len(calls) == 1
