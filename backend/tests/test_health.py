from fastapi.testclient import TestClient

from app.main import create_app


def test_health_ok():
    with TestClient(create_app()) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]


def test_openapi_served():
    with TestClient(create_app()) as client:
        resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert "/api/health" in resp.json()["paths"]
