from app.auth.schemas import SessionSummary
from app.config import SESSION_COOKIE_NAME
from app.db import Database
from app.kb.index import load_ready_chunks
from app.kb.service import IndexingService
from app.models import Assistant
from conftest import ControlledEmbedder, make_pdf
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select


def test_document_metadata_mutations_and_index_are_tenant_isolated(
    auth_client: TestClient,
    second_auth_client: TestClient,
    registered_owner: SessionSummary,
    auth_app: FastAPI,
    auth_database: Database,
    embedding_stub: ControlledEmbedder,
) -> None:
    created = second_auth_client.post(
        "/api/auth/register",
        json={
            "organization_name": "Acme Documents",
            "full_name": "Another Owner",
            "email": "other-docs@example.com",
            "password": "A different test pass 123!",
        },
    )
    assert created.status_code == 201
    other_org = created.json()["organization"]["id"]
    first = auth_client.post(
        "/api/documents",
        files={"file": ("a.pdf", make_pdf("ONLY NORTHBRIDGE EVIDENCE"), "application/pdf")},
    )
    second = second_auth_client.post(
        "/api/documents",
        files={"file": ("b.pdf", make_pdf("ONLY ACME EVIDENCE"), "application/pdf")},
    )
    assert first.status_code == second.status_code == 202
    service = auth_app.state.indexer
    assert isinstance(service, IndexingService) and service.wait_until_idle(timeout=5)
    first_id, second_id = first.json()["id"], second.json()["id"]
    assert [doc["id"] for doc in auth_client.get("/api/documents").json()["documents"]] == [
        first_id
    ]
    assert [doc["id"] for doc in second_auth_client.get("/api/documents").json()["documents"]] == [
        second_id
    ]
    assert auth_client.get(f"/api/documents/{second_id}").status_code == 404
    assert auth_client.delete(f"/api/documents/{second_id}").status_code == 404
    assert (
        auth_client.put(
            f"/api/documents/{second_id}",
            files={"file": ("evil.pdf", make_pdf(), "application/pdf")},
        ).status_code
        == 404
    )
    assert second_auth_client.get(f"/api/documents/{second_id}").json()["status"] == "ready"
    stale_context = {"X-Organization-ID": other_org}
    rejected = [
        auth_client.get("/api/documents", headers=stale_context),
        auth_client.get(f"/api/documents/{first_id}", headers=stale_context),
        auth_client.post("/api/documents", headers=stale_context, content=b"unparsed body"),
        auth_client.put(
            f"/api/documents/{first_id}", headers=stale_context, content=b"unparsed body"
        ),
        auth_client.delete(f"/api/documents/{first_id}", headers=stale_context),
    ]
    assert all(response.status_code == 409 for response in rejected)
    assert all(response.json()["error"]["code"] == "workspace_changed" for response in rejected)
    assert (
        auth_client.get(
            "/api/documents", headers={"X-Organization-ID": registered_owner.organization.id}
        ).json()["used"]
        == 1
    )
    with auth_database.session_factory() as db:
        first_chunks = load_ready_chunks(
            db, registered_owner.organization.id, embedding_stub.model_name
        )
        second_chunks = load_ready_chunks(db, other_org, embedding_stub.model_name)
        assert all("ONLY NORTHBRIDGE" in item.text for item in first_chunks)
        assert all("ONLY ACME" in item.text for item in second_chunks)
        assert len(first_chunks) == len(second_chunks) == 1


def test_assistant_tokens_cannot_list_or_upload_documents(
    auth_client: TestClient,
    second_auth_client: TestClient,
    registered_owner: SessionSummary,
    auth_database: Database,
) -> None:
    with auth_database.session_factory() as db:
        token = db.scalar(
            select(Assistant.token).where(Assistant.org_id == registered_owner.organization.id)
        )
    assert token is not None
    headers = {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}
    assert second_auth_client.get("/api/documents", headers=headers).status_code == 401
    assert (
        second_auth_client.post(
            "/api/documents",
            headers=headers,
            files={"file": ("policy.pdf", make_pdf(), "application/pdf")},
        ).status_code
        == 401
    )
