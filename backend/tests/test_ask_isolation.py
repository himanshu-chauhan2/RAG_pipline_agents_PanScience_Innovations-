from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.main import create_app
from tests.conftest import ControlledEmbedder
from tests.test_ask import FakeGenerator, LexicalReranker, seed_sample_org


@pytest.fixture
def generator() -> FakeGenerator:
    return FakeGenerator()


@pytest.fixture
def app_and_client(
    auth_settings: Settings, generator: FakeGenerator
) -> Iterator[tuple[FastAPI, TestClient]]:
    application = create_app(
        auth_settings,
        embedder=ControlledEmbedder(),
        reranker=LexicalReranker(),
        answer_generator=generator,
    )
    with TestClient(application) as client:
        yield application, client


@pytest.fixture
def tokens(app_and_client: tuple[FastAPI, TestClient]) -> dict[str, str]:
    database: Database = app_and_client[0].state.database
    return {
        "nb": seed_sample_org(database, "northbridge-university"),
        "acme": seed_sample_org(database, "acme-logistics"),
    }


def post(client: TestClient, token: str, question: str) -> dict:
    response = client.post("/api/ask", json={"token": token, "question": question})
    assert response.status_code == 200, response.text
    return response.json()


def test_other_tenant_policy_is_not_answerable(
    app_and_client: tuple[FastAPI, TestClient], tokens: dict[str, str], generator: FakeGenerator
) -> None:
    client = app_and_client[1]
    body = post(
        client,
        tokens["acme"],
        "What GPA does Northbridge University require for its Merit Scholarship?",
    )
    assert body["status"] == "insufficient_evidence"
    assert "3.50" not in body["answer"]
    decision = post(
        client,
        tokens["acme"],
        "Am I eligible for the Merit Scholarship with GPA 3.9 in year 3 and no scholarships?",
    )
    assert decision["status"] == "insufficient_evidence"
    assert decision["decision_trace"] is None
    remote = post(
        client,
        tokens["nb"],
        "I am an analyst with 9 months of service and a rating of "
        "4.0. Am I eligible to request remote work?",
    )
    assert remote["status"] == "insufficient_evidence"
    assert generator.calls == []


def test_citations_only_come_from_the_token_organisation(
    app_and_client: tuple[FastAPI, TestClient], tokens: dict[str, str], generator: FakeGenerator
) -> None:
    client = app_and_client[1]
    body = post(
        client,
        tokens["acme"],
        "I am an analyst with exactly 6 months of service and a "
        "rating of 3.0. Am I eligible to request remote work?",
    )
    assert body["decision_trace"]["verdict"] == "eligible"
    assert {c["document_name"] for c in body["references"]} == {"Remote_Work_Policy.pdf"}
    assert {c["page"] for c in body["references"]} == {1, 2}
    post(client, tokens["acme"], "How many annual-leave days does a full-time employee receive?")
    sent = [source.document_name for _, sources in generator.calls for source in sources]
    assert sent and set(sent) <= {
        "Leave_Policy.pdf",
        "Remote_Work_Policy.pdf",
        "Travel_Reimbursement.pdf",
    }


def test_processing_documents_are_not_searchable(
    app_and_client: tuple[FastAPI, TestClient],
) -> None:
    application, client = app_and_client
    token = seed_sample_org(application.state.database, "acme-logistics", status="processing")
    body = post(client, token, "How many annual-leave days does a full-time employee receive?")
    assert body["status"] == "insufficient_evidence"
