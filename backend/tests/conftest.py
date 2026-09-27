import os
from collections.abc import Iterator, Sequence
from io import BytesIO
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from app.auth import security
from app.auth.schemas import SessionSummary
from app.config import Settings
from app.db import Database
from app.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from numpy.typing import NDArray
from pydantic import SecretStr
from reportlab.pdfgen.canvas import Canvas


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith(
            (
                "LLM_",
                "MODEL_",
                "MODELS_",
                "EMBEDDING_",
                "RERANKER_",
                "AUTH_",
                "DATABASE_",
                "UPLOADS_",
            )
        ):
            monkeypatch.delenv(name)


@pytest.fixture
def auth_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_path=tmp_path / "accounts.db",
        uploads_dir=tmp_path / "uploads",
        auth_secret_key=SecretStr("test-only-signing-key-with-at-least-32-bytes"),
        auth_secret_file=tmp_path / "auth-signing.key",
    )


class ControlledEmbedder:
    model_name = "test-local-embedding"
    dimensions = 4

    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()
        self.release.set()
        self.failure: Exception | None = None
        self.output: NDArray[np.float32] | None = None
        self.calls: list[list[str]] = []

    def embed_documents(self, texts: Sequence[str]) -> NDArray[np.float32]:
        self.calls.append(list(texts))
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("Test embedder was not released.")
        if self.failure is not None:
            raise self.failure
        if self.output is not None:
            return self.output
        return np.tile(np.array([1, 2, 3, 4], dtype=np.float32), (len(texts), 1))


def make_pdf(text: str = "A searchable test policy.", pages: int = 1) -> bytes:
    output = BytesIO()
    canvas = Canvas(output, invariant=1, pageCompression=0)
    for page in range(1, pages + 1):
        if text:
            canvas.drawString(40, 780, f"Page {page}: {text}")
        canvas.showPage()
    canvas.save()
    return output.getvalue()


def pad_pdf(content: bytes, target_size: int) -> bytes:
    extra = target_size - len(content)
    assert extra >= 2
    position = content.rindex(b"startxref")
    result = content[:position] + b"%" + b"x" * (extra - 2) + b"\n" + content[position:]
    assert len(result) == target_size
    return result


@pytest.fixture
def embedding_stub() -> ControlledEmbedder:
    return ControlledEmbedder()


@pytest.fixture
def auth_app(
    auth_settings: Settings, monkeypatch: pytest.MonkeyPatch, embedding_stub: ControlledEmbedder
) -> FastAPI:
    monkeypatch.setattr(security, "PASSWORD_ROUNDS", 4)
    return create_app(auth_settings, embedder=embedding_stub)


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
