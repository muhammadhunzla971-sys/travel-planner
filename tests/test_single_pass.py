from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from tests.fakes import ER_API, all_down, patch_all


def body(**over):
    start = date.today() + timedelta(days=30)
    data = {"budget": 2500, "currency": "USD", "origin": "Lahore", "destination": "Istanbul",
            "start_date": start.isoformat(), "end_date": (start + timedelta(days=5)).isoformat(),
            "travelers": 2}
    data.update(over)
    return data


def test_agents_preview_runs_every_agent_even_when_providers_and_llm_are_down(monkeypatch):
    all_down(monkeypatch)
    r = TestClient(app).post("/api/agents/preview", json=body())
    assert r.status_code == 200
    data = r.json()
    assert [p["agent"] for p in data["proposals"]] == ["flight", "stay", "activities"]
    assert all(p["used_llm"] is False for p in data["proposals"])
    trip = data["trip"]
    assert trip["selected_flight"] and trip["selected_stay"] and trip["days"]
    assert len(trip["messages"]) == 4  # 3 proposals + critic
    assert trip["messages"][-1]["from_agent"] == "critic"
    assert data["total_cost"] == round(sum(line["amount"] for line in
                                           [{"amount": trip["selected_flight"]["total_price"]},
                                            {"amount": trip["selected_stay"]["total_price"]},
                                            {"amount": sum(i["cost"] for d in trip["days"] for i in d["items"])},
                                            {"amount": trip["food_transport_estimate"]}]), 2)
    assert data["within_budget"] == (data["total_cost"] <= 2500)
    assert data["review"]["verdict"]
    assert trip["status"] in {"completed", "completed_with_warnings"}


def test_agents_preview_flags_a_tiny_budget_instead_of_crashing(monkeypatch):
    all_down(monkeypatch)
    r = TestClient(app).post("/api/agents/preview", json=body(budget=100))
    assert r.status_code == 200
    data = r.json()
    assert any(c["kind"] == "infeasible" for c in data["review"]["conflicts"])
    assert data["trip"]["status"] == "completed_with_warnings"


def test_agents_preview_error_codes(monkeypatch):
    client = TestClient(app)
    patch_all(monkeypatch, {"geocoding-api": {"generationtime_ms": 1}, "er-api": ER_API})
    assert client.post("/api/agents/preview", json=body(destination="Atlantis")).status_code == 422
    all_down(monkeypatch)
    assert client.post("/api/agents/preview", json=body(destination="Zzyzx Springs")).status_code == 503


def test_llm_check_endpoint_reports_missing_key_without_crashing():
    r = TestClient(app).get("/api/llm/check")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False and data["key_configured"] is False
    assert "GROQ_API_KEY" in data["error"]
