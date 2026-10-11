import json
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.services.trip_data import DataUnavailable, DestinationNotFound
from tests.fakes import ER_API, FORECAST, GEOCODE_ISTANBUL, WIKI_ISTANBUL, patch_all

client = TestClient(app)


def _body(**kw):
    start = date.today() + timedelta(days=40)
    body = {"budget": 2500, "currency": "USD", "origin": "Lahore", "destination": "Istanbul",
            "start_date": start.isoformat(), "end_date": (start + timedelta(days=6)).isoformat(),
            "travelers": 2}
    body.update(kw)
    return body


def parse_sse(text: str) -> list[tuple[str, object]]:
    out = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        ev, data = None, ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        if ev:
            out.append((ev, json.loads(data)))
    return out


def test_home_page_is_the_website():
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "AI Travel Planner" in r.text and "/api/plan/stream" in r.text
    assert "api_key" not in r.text.lower()


def test_api_info_still_available():
    assert client.get("/api-info").json()["docs"] == "/docs"


def test_stream_sends_steps_then_the_result(monkeypatch):
    patch_all(monkeypatch, {"geocoding-api": GEOCODE_ISTANBUL, "er-api": ER_API,
                            "api.open-meteo.com": FORECAST, "archive-api": FORECAST,
                            "wikipedia": WIKI_ISTANBUL})
    r = client.post("/api/plan/stream", json=_body())
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    kinds = [k for k, _ in events]
    assert kinds[0] == "start" and kinds[-1] == "result" and "error" not in kinds
    steps = [d for k, d in events if k == "step"]
    assert len(steps) >= 5 and steps[0]["stage"] == "research" and steps[-1]["stage"] == "final"
    assert [s["seq"] for s in steps] == list(range(1, len(steps) + 1))
    result = events[-1][1]
    assert result["trip"]["status"] == "completed" and result["breakdown"]["total_cost"] > 0
    assert len(result["timeline"]) == len(steps)  # same events, streamed live


def test_stream_reports_unknown_destination_as_an_error_event(monkeypatch):
    async def boom(request, data=None, on_event=None):
        raise DestinationNotFound("Could not find 'Nowhereville'")

    monkeypatch.setattr("app.api.routes.plan_trip", boom)
    events = parse_sse(client.post("/api/plan/stream", json=_body(destination="Nowhereville")).text)
    assert events[-1][0] == "error" and events[-1][1]["status"] == 422
    assert "Nowhereville" in events[-1][1]["detail"]


def test_stream_reports_data_outage_and_crashes_without_hanging(monkeypatch):
    async def down(request, data=None, on_event=None):
        raise DataUnavailable("providers down")

    monkeypatch.setattr("app.api.routes.plan_trip", down)
    ev = parse_sse(client.post("/api/plan/stream", json=_body()).text)
    assert ev[-1] == ("error", {"status": 503, "detail": "providers down"})

    async def crash(request, data=None, on_event=None):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr("app.api.routes.plan_trip", crash)
    ev = parse_sse(client.post("/api/plan/stream", json=_body()).text)
    assert ev[-1][0] == "error" and "secret" not in json.dumps(ev[-1][1])


def test_stream_rejects_invalid_requests_normally():
    r = client.post("/api/plan/stream", json=_body(budget=-5))
    assert r.status_code == 422


def test_public_config_is_empty_until_supabase_is_configured(monkeypatch):
    from app.config import get_settings
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "")
    get_settings.cache_clear()
    assert TestClient(app).get("/api/config").json() == {"supabase_url": None, "supabase_anon_key": None}
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    get_settings.cache_clear()
    assert TestClient(app).get("/api/config").json() == {"supabase_url": "https://x.supabase.co",
                                                         "supabase_anon_key": "anon"}
    get_settings.cache_clear()


def test_home_page_has_map_accounts_and_meals():
    html = TestClient(app).get("/").text
    for needle in ("drawMap", "initAccounts", "saveTrip", "leaflet", "m.slot"):
        assert needle in html


def test_home_page_has_dietary_field_sent_with_the_request():
    html = TestClient(app).get("/").text
    assert 'id="diet"' in html and "dietary_needs" in html
