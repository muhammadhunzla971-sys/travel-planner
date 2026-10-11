from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _body(**overrides):
    start = date.today() + timedelta(days=30)
    body = {
        "budget": 2000,
        "currency": "USD",
        "destination": "Istanbul",
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=5)).isoformat(),
        "travelers": 2,
    }
    body.update(overrides)
    return body


def test_budget_preview_ok():
    r = client.post("/api/budget/preview", json=_body())
    assert r.status_code == 200
    data = r.json()
    assert data["nights"] == 5
    assert abs(sum(data["allocation"].values()) - 2000) < 0.02


def test_budget_preview_cost_level_query():
    r = client.post("/api/budget/preview?cost_level=high", json=_body())
    assert r.status_code == 200
    assert r.json()["cost_level"] == "high"


def test_budget_preview_rejects_bad_dates():
    past = (date.today() - timedelta(days=5)).isoformat()
    r = client.post("/api/budget/preview", json=_body(start_date=past))
    assert r.status_code == 422
