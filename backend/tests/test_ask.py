import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.ask.service import AskService
from app.config import Settings
from app.db import Database
from app.llm.answer import AnswerCitation, GeneratedAnswer, SourceText
from app.main import create_app
from app.models import Assistant, Chunk, Document, Organization, QuestionLog
from app.retrieval.text import sentences, tokens
from tests.conftest import ControlledEmbedder

SAMPLE = Path(__file__).resolve().parents[2] / "sample_data"


class LexicalReranker:
    model_name = "test-lexical-reranker"

    def __init__(self) -> None:
        self.calls = 0

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        self.calls += 1
        wanted = set(tokens(query))
        return [8 * len(wanted & set(tokens(text))) / max(1, len(wanted)) - 4 for text in texts]


class FakeGenerator:
    """Quotes the source sentence with the largest word overlap; never calls a network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[SourceText]]] = []
        self.fabricate = False

    async def generate(
        self, question: str, history: Sequence[tuple[str, str]], sources: Sequence[SourceText]
    ) -> GeneratedAnswer:
        self.calls.append((question, list(sources)))
        wanted = set(tokens(question))
        best = max(
            ((s, sentence) for s in sources for sentence in sentences(s.text)),
            key=lambda pair: len(wanted & set(tokens(pair[1]))),
        )
        quote = "The policy guarantees free meals." if self.fabricate else best[1]
        return GeneratedAnswer(
            status="answered",
            answer=f"According to the policy: {quote}",
            citations=[AnswerCitation(source_id=best[0].source_id, quote=quote)],
        )


def seed_sample_org(database: Database, slug: str, status: str = "ready") -> str:
    """Store one sample organisation's policy pages as indexed chunks; returns the token."""
    policies = yaml.safe_load((SAMPLE / "policies.yaml").read_text(encoding="utf-8"))
    organization = next(o for o in policies["organizations"] if o["slug"] == slug)
    token = f"tok-{slug}-{uuid4().hex}"
    with database.session_factory() as db:
        org = Organization(id=str(uuid4()), name=organization["name"])
        db.add(org)
        db.flush()
        db.add(Assistant(id=str(uuid4()), org_id=org.id, token=token))
        for document in organization["documents"]:
            doc = Document(
                id=str(uuid4()),
                org_id=org.id,
                name=document["filename"],
                pages=len(document["pages"]),
                size_bytes=1000,
                storage_key=uuid4().hex,
                revision=uuid4().hex,
                status=status,
                chunk_count=len(document["pages"]),
                embedding_model="test-local-embedding",
                embedding_dimensions=4,
            )
            db.add(doc)
            db.flush()
            for page, content in enumerate(document["pages"], 1):
                text = " ".join([content["heading"], *content["paragraphs"]])
                db.add(
                    Chunk(
                        id=str(uuid4()),
                        org_id=org.id,
                        document_id=doc.id,
                        ordinal=page - 1,
                        page=page,
                        text=text,
                        embedding=np.array([1, 2, 3, 4], dtype="<f4").tobytes(),
                    )
                )
        db.commit()
    return token


def quoted_in_org(database: Database, token: str, quote: str) -> bool:
    with database.session_factory() as db:
        org_id = db.query(Assistant.org_id).filter(Assistant.token == token).scalar()
        texts = [c.text for c in db.query(Chunk).filter(Chunk.org_id == org_id)]
    return any(re.sub(r"\s+", " ", quote) in text for text in texts)


@pytest.fixture
def generator() -> FakeGenerator:
    return FakeGenerator()


@pytest.fixture
def ask_app(auth_settings: Settings, generator: FakeGenerator) -> FastAPI:
    return create_app(
        auth_settings,
        embedder=ControlledEmbedder(),
        reranker=LexicalReranker(),
        answer_generator=generator,
    )


@pytest.fixture
def client(ask_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(ask_app) as test_client:
        yield test_client


@pytest.fixture
def database(ask_app: FastAPI, client: TestClient) -> Database:
    return ask_app.state.database


@pytest.fixture
def nb_token(database: Database) -> str:
    return seed_sample_org(database, "northbridge-university")


def ask(client: TestClient, token: str, question: str, history: list | None = None) -> dict:
    response = client.post(
        "/api/ask", json={"token": token, "question": question, "history": history or []}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_question_log_storage_failure_is_not_reported_as_success(
    client: TestClient, nb_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_log(*_args: object) -> None:
        raise SQLAlchemyError("simulated log storage outage")

    monkeypatch.setattr(AskService, "_log", failed_log)
    response = client.post(
        "/api/ask",
        json={
            "token": nb_token,
            "question": (
                "I am in year 2 with GPA 3.6 and a sports scholarship. "
                "Am I eligible for the Merit Scholarship?"
            ),
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_unavailable"


def test_unknown_token_is_rejected(client: TestClient) -> None:
    response = client.post("/api/ask", json={"token": "nope", "question": "Hello?"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_assistant_token"


def test_blank_question_is_rejected(client: TestClient, nb_token: str) -> None:
    response = client.post("/api/ask", json={"token": nb_token, "question": "   "})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_input"


def test_sports_scholarship_decision_is_deterministic_and_cited(
    client: TestClient, nb_token: str, generator: FakeGenerator, database: Database
) -> None:
    body = ask(
        client,
        nb_token,
        "I am in year 2, my GPA is 3.6 out of 4, and I hold a sports scholarship. "
        "Am I eligible for the Merit Scholarship?",
    )
    assert body["status"] == "answered"
    assert body["classification"]["category"] == "multi_condition"
    decision = body["decision_trace"]
    assert decision["verdict"] == "not_eligible"
    assert {c["id"]: c["result"] for c in decision["checks"]} == {
        "year_met": True,
        "gpa_met": True,
        "stacking_met": False,
    }
    assert decision["score"] == pytest.approx(0.667)
    assert {(c["document_name"], c["page"]) for c in body["references"]} == {
        ("Scholarship_Rules.pdf", 1)
    }
    ids = {c["id"] for c in body["references"]}
    assert all(set(c["reference_ids"]) <= ids for c in decision["checks"])
    assert all(quoted_in_org(database, nb_token, c["quote"]) for c in body["references"])
    assert generator.calls == []
    assert [step["step"] for step in body["trace"]][:2] == ["tenant", "rules"]


def test_missing_gpa_then_clarification(client: TestClient, nb_token: str) -> None:
    first_question = (
        "I am a second-year student with no existing scholarships. "
        "Can I qualify for the Merit Scholarship?"
    )
    first = ask(client, nb_token, first_question)
    assert first["status"] == "needs_info"
    assert first["decision_trace"]["missing_fields"] == ["gpa"]
    assert "GPA" in first["follow_up_question"]
    second = ask(
        client,
        nb_token,
        "3.6",
        [
            {"role": "user", "content": first_question},
            {"role": "assistant", "content": first["answer"]},
        ],
    )
    assert second["status"] == "answered"
    assert second["decision_trace"]["verdict"] == "eligible"


def test_need_based_award_is_allowed(client: TestClient, nb_token: str) -> None:
    body = ask(
        client,
        nb_token,
        "Can I get the Merit Scholarship as a third-year student with a 3.7 GPA and only a "
        "need-based award?",
    )
    assert body["decision_trace"]["verdict"] == "eligible"


def test_direct_question_uses_generator_with_verified_citations(
    client: TestClient, nb_token: str, generator: FakeGenerator, database: Database
) -> None:
    body = ask(client, nb_token, "On what date does the 2026 Merit Scholarship application close?")
    assert body["status"] == "answered"
    assert body["decision_trace"] is None
    assert len(generator.calls) == 1
    assert body["references"][0]["document_name"] == "Scholarship_Rules.pdf"
    assert body["references"][0]["page"] == 3
    assert "31 August 2026" in body["references"][0]["quote"]
    assert quoted_in_org(database, nb_token, body["references"][0]["quote"])


def test_fabricated_quote_is_an_explicit_error(
    client: TestClient, nb_token: str, generator: FakeGenerator
) -> None:
    generator.fabricate = True
    response = client.post(
        "/api/ask", json={"token": nb_token, "question": "At what times are hostel quiet hours?"}
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "ungrounded_answer"


def test_absent_topic_returns_insufficient_evidence_without_llm(
    client: TestClient, nb_token: str, generator: FakeGenerator, database: Database
) -> None:
    body = ask(client, nb_token, "Will it rain in Northbridge tomorrow afternoon?")
    assert body["status"] == "insufficient_evidence"
    assert body["references"] == []
    assert generator.calls == []
    with database.session_factory() as db:
        logs = db.query(QuestionLog).all()
    assert [log.status for log in logs] == ["insufficient_evidence"]


def test_unconfigured_gateway_fails_explicitly(auth_settings: Settings) -> None:
    application = create_app(
        auth_settings, embedder=ControlledEmbedder(), reranker=LexicalReranker()
    )
    with TestClient(application) as test_client:
        token = seed_sample_org(application.state.database, "northbridge-university")
        response = test_client.post(
            "/api/ask", json={"token": token, "question": "At what times are hostel quiet hours?"}
        )
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "llm_unavailable"
    assert "key" not in error["message"].lower()


def test_owner_reads_own_assistant_token_and_can_ask(
    auth_client: TestClient, registration_payload: dict[str, str]
) -> None:
    assert auth_client.get("/api/assistant").status_code == 401
    registered = auth_client.post("/api/auth/register", json=registration_payload)
    assert registered.status_code == 201
    link = auth_client.get("/api/assistant")
    assert link.status_code == 200
    body = link.json()
    assert body["organization_id"] == registered.json()["organization"]["id"]
    assert body["ask_endpoint"] == "/api/ask"
    assert body["public_path"] == f"/a/{body['token']}"
    auth_client.cookies.clear()
    answer = auth_client.post("/api/ask", json={"token": body["token"], "question": "Hello?"})
    assert answer.status_code == 200
    assert answer.json()["status"] == "insufficient_evidence"
    assert {"status", "verdict", "references", "decision_trace"} <= answer.json().keys()


def test_rate_limits_are_per_assistant_and_explicit(
    ask_app: FastAPI, client: TestClient, database: Database, generator: FakeGenerator
) -> None:
    from app.ask.limits import TokenBucket

    now = [0.0]
    service = ask_app.state.ask_service
    service.answer_limit = TokenBucket(2, 60, "generated answers", clock=lambda: now[0])
    service.request_limit = TokenBucket(4, 60, "questions", clock=lambda: now[0])
    nb = seed_sample_org(database, "northbridge-university")
    acme = seed_sample_org(database, "acme-logistics")
    question = {"token": nb, "question": "At what times are hostel quiet hours?"}
    assert client.post("/api/ask", json=question).status_code == 200
    assert client.post("/api/ask", json=question).status_code == 200
    limited = client.post("/api/ask", json=question)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"
    assert len(generator.calls) == 2
    # Local-only paths still work until the overall request budget is spent.
    weather = {"token": nb, "question": "Will it rain tomorrow?"}
    assert client.post("/api/ask", json=weather).status_code == 200
    assert client.post("/api/ask", json=weather).status_code == 429
    other = {"token": acme, "question": "How many annual-leave days do employees receive?"}
    assert client.post("/api/ask", json=other).status_code == 200
    now[0] = 60.0
    assert client.post("/api/ask", json=question).status_code == 200


def test_unknown_token_reveals_no_document_content(client: TestClient, nb_token: str) -> None:
    response = client.post("/api/ask", json={"token": nb_token + "x", "question": "quiet hours"})
    assert response.status_code == 401
    assert set(response.json()) == {"error"}
    assert "Quiet" not in response.text


def test_assistant_link_rejects_a_stale_workspace_header(
    auth_client: TestClient, registration_payload: dict[str, str]
) -> None:
    registered = auth_client.post("/api/auth/register", json=registration_payload)
    assert registered.status_code == 201
    org_id = registered.json()["organization"]["id"]
    assert (
        auth_client.get("/api/assistant", headers={"X-Organization-ID": org_id}).status_code == 200
    )
    stale = auth_client.get("/api/assistant", headers={"X-Organization-ID": "other-org"})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "workspace_changed"
    assert "token" not in stale.text
