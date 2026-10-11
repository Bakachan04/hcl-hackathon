from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_api_store_and_llm():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["api"] == "ok"
    assert body["data_store"] in {"ok", "empty"}
    assert body["llm"] in {"mock", "missing_key", "configured"}
