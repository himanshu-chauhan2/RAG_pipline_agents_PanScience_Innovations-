from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_health_response_contract() -> None:
    client = TestClient(create_app(Settings(_env_file=None)))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "knowledge-decision-assistant",
        "version": "0.1.0",
        "phase": "P1",
        "gateway_configured": False,
    }


def test_health_exposes_neither_key_nor_gateway_url() -> None:
    settings = Settings(
        _env_file=None,
        llm_base_url="https://gateway.example.test/v1",
        llm_api_key="private-test-value",
    )
    response = TestClient(create_app(settings)).get("/api/health")
    assert response.json()["gateway_configured"] is True
    assert "private-test-value" not in response.text
    assert "gateway.example.test" not in response.text


def test_openapi_documents_the_real_health_endpoint() -> None:
    client = TestClient(create_app(Settings(_env_file=None)))
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]


def test_unimplemented_ask_api_is_not_a_fake_success() -> None:
    client = TestClient(create_app(Settings(_env_file=None)))
    assert client.post("/api/ask", json={"token": "demo", "question": "Hello"}).status_code == 404
