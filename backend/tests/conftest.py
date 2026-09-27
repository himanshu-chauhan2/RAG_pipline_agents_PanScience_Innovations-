import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from app.auth import security
from app.auth.schemas import SessionSummary
from app.config import Settings
from app.db import Database
from app.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith(
            ("LLM_", "MODEL_", "MODELS_", "EMBEDDING_", "RERANKER_", "AUTH_", "DATABASE_")
        ):
            monkeypatch.delenv(name)


@pytest.fixture
def auth_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_path=tmp_path / "accounts.db",
        auth_secret_key=SecretStr("test-only-signing-key-with-at-least-32-bytes"),
        auth_secret_file=tmp_path / "auth-signing.key",
    )


@pytest.fixture
def auth_app(auth_settings: Settings, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(security, "PASSWORD_ROUNDS", 4)
    return create_app(auth_settings)


@pytest.fixture
def auth_client(auth_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(auth_app, headers={"Origin": "http://127.0.0.1:5173"}) as client:
        yield client


@pytest.fixture
def second_auth_client(auth_app: FastAPI, auth_client: TestClient) -> Iterator[TestClient]:
    client = TestClient(auth_app, headers={"Origin": "http://127.0.0.1:5173"})
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def auth_database(auth_app: FastAPI, auth_client: TestClient) -> Database:
    database = auth_app.state.database
    assert isinstance(database, Database)
    return database


@pytest.fixture
def registration_payload() -> dict[str, str]:
    return {
        "organization_name": "Northbridge Test",
        "full_name": "Alex Owner",
        "email": "alex@example.com",
        "password": "Correct horse 123!",
    }


@pytest.fixture
def registered_owner(
    auth_client: TestClient, registration_payload: dict[str, str]
) -> SessionSummary:
    response = auth_client.post("/api/auth/register", json=registration_payload)
    assert response.status_code == 201, response.text
    return SessionSummary.model_validate(response.json())
