from fastapi.testclient import TestClient

from app.main import app


def test_health_exposes_the_safe_runtime_flags():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["live_trading_enabled"] is False
    assert body["auth_provider"] == "dev_mock"
    assert response.headers["x-request-id"]


def test_ready_checks_the_database(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
