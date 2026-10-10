import httpx
import pytest

from app.tools import cache as cache_module
from app.tools.cache import TTLCache, make_key
from app.tools.http import ProviderError, fetch_json


# ---- cache ---------------------------------------------------------------
def test_cache_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(cache_module.time, "monotonic", lambda: now[0])
    c = TTLCache()
    c.set("a", 1, ttl=10)
    assert c.get("a") == 1
    now[0] += 11
    assert c.get("a") is None


async def test_get_or_set_calls_factory_once():
    c = TTLCache()
    calls = []

    async def factory():
        calls.append(1)
        return "value"

    assert await c.get_or_set("k", 60, factory) == "value"
    assert await c.get_or_set("k", 60, factory) == "value"
    assert len(calls) == 1


async def test_none_is_not_cached():
    c = TTLCache()
    calls = []

    async def factory():
        calls.append(1)

    await c.get_or_set("k", 60, factory)
    await c.get_or_set("k", 60, factory)
    assert len(calls) == 2


def test_cache_evicts_when_full():
    c = TTLCache(max_items=2)
    c.set("a", 1, 10)
    c.set("b", 2, 20)
    c.set("c", 3, 30)
    assert c.get("c") == 3
    assert len([k for k in "abc" if c.get(k) is not None]) == 2


def test_make_key_is_case_and_space_insensitive():
    assert make_key("geocode", " Istanbul ") == make_key("GEOCODE", "istanbul")


# ---- http ----------------------------------------------------------------
def _transport(handler):
    return httpx.MockTransport(handler)


async def test_fetch_json_ok():
    t = _transport(lambda req: httpx.Response(200, json={"ok": True}))
    assert await fetch_json("https://x.test/a", transport=t, backoff=0) == {"ok": True}


async def test_fetch_json_retries_then_succeeds():
    attempts = []

    def handler(req):
        attempts.append(1)
        return httpx.Response(500) if len(attempts) < 3 else httpx.Response(200, json={"n": 3})

    result = await fetch_json("https://x.test/a", transport=_transport(handler), backoff=0)
    assert result == {"n": 3}
    assert len(attempts) == 3


async def test_fetch_json_gives_up_with_provider_error():
    attempts = []

    def handler(req):
        attempts.append(1)
        return httpx.Response(503)

    with pytest.raises(ProviderError):
        await fetch_json("https://x.test/a", transport=_transport(handler), backoff=0, retries=2)
    assert len(attempts) == 3


async def test_fetch_json_bad_json_and_404_are_provider_errors():
    with pytest.raises(ProviderError):
        await fetch_json("https://x.test/a", backoff=0, retries=0,
                         transport=_transport(lambda r: httpx.Response(200, text="not json")))
    with pytest.raises(ProviderError):
        await fetch_json("https://x.test/a", backoff=0, retries=0,
                         transport=_transport(lambda r: httpx.Response(404)))
