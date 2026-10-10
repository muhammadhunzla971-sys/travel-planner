from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_version_never_leaks_keys():
    r = client.get("/version")
    assert r.status_code == 200
    body = r.json()
    assert "llm_key_configured" in body
    assert "api_key" not in str(body).lower()
