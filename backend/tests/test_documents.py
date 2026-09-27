from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import numpy as np
import pytest
from app.auth.schemas import SessionSummary
from app.config import Settings
from app.db import Database
from app.kb.index import IndexReadError, load_ready_chunks
from app.kb.schemas import DocumentSummary
from app.kb.service import IndexingService
from app.kb.storage import StorageError
from app.models import Chunk, Document
from conftest import ControlledEmbedder, make_pdf
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError, OperationalError


@pytest.fixture
def indexer(auth_app: FastAPI, auth_client: TestClient) -> IndexingService:
    service = auth_app.state.indexer
    assert isinstance(service, IndexingService)
    return service


def upload(client: TestClient, name: str = "policy.pdf", text: str = "Original policy."):
    return client.post("/api/documents", files={"file": (name, make_pdf(text), "application/pdf")})


def ready(client: TestClient, indexer: IndexingService, response) -> DocumentSummary:
    assert response.status_code == 202, response.text
    assert indexer.wait_until_idle(timeout=5)
    current = client.get(f"/api/documents/{response.json()['id']}")
    assert current.status_code == 200
    result = DocumentSummary.model_validate(current.json())
    assert result.status == "ready", result
    return result


def test_upload_list_private_storage_and_page_index(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
    auth_database: Database,
    auth_settings: Settings,
    embedding_stub: ControlledEmbedder,
) -> None:
    document = ready(auth_client, indexer, upload(auth_client))
    assert document.pages == 1 and document.chunk_count == 1
    assert document.error is None and document.replacement is None
    result = auth_client.get("/api/documents").json()
    assert result["used"] == 1
    assert (result["max_documents"], result["max_pages"], result["max_size_bytes"]) == (
        10,
        20,
        10_000_000,
    )
    assert "storage_key" not in result["documents"][0]
    assert "embedding" not in result["documents"][0]
    files = list(auth_settings.uploads_dir.iterdir())
    assert len(files) == 1 and files[0].name != "policy.pdf"
    assert files[0].read_bytes().startswith(b"%PDF-")
    assert auth_client.get(f"/uploads/{files[0].name}").status_code == 404
    assert auth_client.get(f"/api/documents/{document.id}/download").status_code == 404
    with auth_database.session_factory() as db:
        chunks = load_ready_chunks(db, registered_owner.organization.id, embedding_stub.model_name)
        assert len(chunks) == 1 and chunks[0].page == 1
        assert chunks[0].document_name == "policy.pdf"
        assert "Original policy." in chunks[0].text
        np.testing.assert_allclose(np.linalg.norm(chunks[0].embedding), 1, atol=1e-6)


def test_processing_documents_are_not_in_the_ready_index(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
    auth_database: Database,
    embedding_stub: ControlledEmbedder,
) -> None:
    embedding_stub.release.clear()
    try:
        response = upload(auth_client)
        assert response.status_code == 202
        assert embedding_stub.entered.wait(timeout=3)
        assert auth_client.get("/api/documents").json()["documents"][0]["status"] == "processing"
        with auth_database.session_factory() as db:
            assert (
                load_ready_chunks(db, registered_owner.organization.id, embedding_stub.model_name)
                == []
            )
    finally:
        embedding_stub.release.set()
    assert indexer.wait_until_idle(timeout=5)


def test_failed_embedding_is_visible_and_consumes_one_slot(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
    embedding_stub: ControlledEmbedder,
    auth_database: Database,
) -> None:
    embedding_stub.failure = RuntimeError("test embedding outage")
    response = upload(auth_client)
    assert response.status_code == 202
    assert indexer.wait_until_idle(timeout=5)
    result = auth_client.get("/api/documents").json()
    assert result["used"] == 1
    assert result["documents"][0]["status"] == "failed"
    assert result["documents"][0]["error"]["code"] == "processing_failed"
    with auth_database.session_factory() as db:
        assert (
            load_ready_chunks(db, registered_owner.organization.id, embedding_stub.model_name) == []
        )
        assert db.scalar(select(func.count()).select_from(Chunk)) == 0


def test_atomic_replacement_keeps_old_index_until_success(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
    embedding_stub: ControlledEmbedder,
    auth_database: Database,
    auth_settings: Settings,
) -> None:
    original = ready(auth_client, indexer, upload(auth_client))
    original_file = next(auth_settings.uploads_dir.iterdir())
    embedding_stub.entered.clear()
    embedding_stub.release.clear()
    try:
        response = auth_client.put(
            f"/api/documents/{original.id}",
            files={"file": ("replacement.pdf", make_pdf("Replacement policy."), "application/pdf")},
        )
        assert response.status_code == 202
        assert embedding_stub.entered.wait(timeout=3)
        current = response.json()
        assert current["status"] == "ready" and current["name"] == "policy.pdf"
        assert current["replacement"]["status"] == "processing"
        assert auth_client.get("/api/documents").json()["used"] == 1
        with auth_database.session_factory() as db:
            chunks = load_ready_chunks(
                db, registered_owner.organization.id, embedding_stub.model_name
            )
            assert len(chunks) == 1 and "Original policy." in chunks[0].text
        assert len(list(auth_settings.uploads_dir.iterdir())) == 2
        again = auth_client.put(
            f"/api/documents/{original.id}",
            files={"file": ("again.pdf", make_pdf(), "application/pdf")},
        )
        assert again.status_code == 409 and again.json()["error"]["code"] == "document_busy"
    finally:
        embedding_stub.release.set()
    assert indexer.wait_until_idle(timeout=5)
    current = auth_client.get(f"/api/documents/{original.id}").json()
    assert current["status"] == "ready" and current["name"] == "replacement.pdf"
    assert current["replacement"] is None
    assert not original_file.exists()
    assert len(list(auth_settings.uploads_dir.iterdir())) == 1
    with auth_database.session_factory() as db:
        chunks = load_ready_chunks(db, registered_owner.organization.id, embedding_stub.model_name)
        assert len(chunks) == 1 and "Replacement policy." in chunks[0].text
        assert "Original policy." not in chunks[0].text


def test_failed_replacement_preserves_old_file_and_chunks(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
    embedding_stub: ControlledEmbedder,
    auth_database: Database,
    auth_settings: Settings,
) -> None:
    original = ready(auth_client, indexer, upload(auth_client))
    original_file = next(auth_settings.uploads_dir.iterdir())
    original_bytes = original_file.read_bytes()
    embedding_stub.failure = RuntimeError("test failure")
    response = auth_client.put(
        f"/api/documents/{original.id}",
        files={"file": ("new.pdf", make_pdf("New text."), "application/pdf")},
    )
    assert response.status_code == 202 and indexer.wait_until_idle(timeout=5)
    current = auth_client.get(f"/api/documents/{original.id}").json()
    assert current["status"] == "ready" and current["name"] == "policy.pdf"
    assert current["replacement"]["status"] == "failed"
    assert current["replacement"]["error"] is not None
    assert original_file.read_bytes() == original_bytes
    assert len(list(auth_settings.uploads_dir.iterdir())) == 1
    with auth_database.session_factory() as db:
        assert (
            "Original policy."
            in load_ready_chunks(db, registered_owner.organization.id, embedding_stub.model_name)[
                0
            ].text
        )


def test_invalid_replacement_never_changes_existing_metadata(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
) -> None:
    original = ready(auth_client, indexer, upload(auth_client))
    response = auth_client.put(
        f"/api/documents/{original.id}", files={"file": ("invalid.pdf", b"bad", "application/pdf")}
    )
    assert response.status_code == 400
    assert (
        DocumentSummary.model_validate(auth_client.get(f"/api/documents/{original.id}").json())
        == original
    )


@pytest.mark.parametrize("replacement", [False, True])
def test_delete_during_processing_cannot_resurrect_data(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
    embedding_stub: ControlledEmbedder,
    auth_database: Database,
    auth_settings: Settings,
    replacement: bool,
) -> None:
    original = ready(auth_client, indexer, upload(auth_client)) if replacement else None
    embedding_stub.entered.clear()
    embedding_stub.release.clear()
    try:
        if original:
            response = auth_client.put(
                f"/api/documents/{original.id}",
                files={"file": ("new.pdf", make_pdf("New policy."), "application/pdf")},
            )
        else:
            response = upload(auth_client)
        assert response.status_code == 202
        document_id = response.json()["id"]
        assert embedding_stub.entered.wait(timeout=3)
        assert auth_client.delete(f"/api/documents/{document_id}").status_code == 204
        assert auth_client.get("/api/documents").json()["used"] == 0
        assert list(auth_settings.uploads_dir.iterdir()) == []
    finally:
        embedding_stub.release.set()
    assert indexer.wait_until_idle(timeout=5)
    assert auth_client.get(f"/api/documents/{document_id}").status_code == 404
    with auth_database.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Chunk)) == 0


def test_document_quota_replacement_and_reupload_at_capacity(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
) -> None:
    documents = [
        ready(auth_client, indexer, upload(auth_client, f"doc-{number}.pdf"))
        for number in range(10)
    ]
    rejected = upload(auth_client, "eleventh.pdf")
    assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "document_limit"
    assert auth_client.get("/api/documents").json()["used"] == 10
    replacement = auth_client.put(
        f"/api/documents/{documents[0].id}",
        files={"file": ("replaced.pdf", make_pdf("Replaced at capacity."), "application/pdf")},
    )
    assert replacement.status_code == 202 and indexer.wait_until_idle(timeout=5)
    assert auth_client.get("/api/documents").json()["used"] == 10
    assert auth_client.delete(f"/api/documents/{documents[1].id}").status_code == 204
    ready(auth_client, indexer, upload(auth_client, "new-tenth.pdf"))
    assert auth_client.get("/api/documents").json()["used"] == 10


def test_concurrent_uploads_cannot_exceed_tenant_quota(
    auth_client: TestClient,
    second_auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
) -> None:
    assert (
        second_auth_client.post(
            "/api/auth/login", json={"email": "alex@example.com", "password": "Correct horse 123!"}
        ).status_code
        == 200
    )
    for number in range(9):
        ready(auth_client, indexer, upload(auth_client, f"existing-{number}.pdf"))
    barrier = Barrier(2)

    def attempt(client: TestClient) -> int:
        barrier.wait(timeout=5)
        return upload(client, f"candidate-{uuid4().hex}.pdf").status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [auth_client, second_auth_client]))
    assert sorted(results) == [202, 409]
    assert indexer.wait_until_idle(timeout=5)
    assert auth_client.get("/api/documents").json()["used"] == 10


def test_storage_failure_does_not_remove_a_ready_document(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
    auth_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = ready(auth_client, indexer, upload(auth_client))

    def fail_delete(key: str) -> None:
        raise StorageError("injected private storage failure")

    monkeypatch.setattr(indexer.storage, "discard", fail_delete)
    response = auth_client.delete(f"/api/documents/{original.id}")
    assert response.status_code == 503
    assert auth_client.get(f"/api/documents/{original.id}").json()["status"] == "ready"
    with auth_database.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Chunk)) == 1


def test_database_failure_restores_deleted_pdf_bytes(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
    auth_database: Database,
    auth_settings: Settings,
) -> None:
    original = ready(auth_client, indexer, upload(auth_client))
    path = next(auth_settings.uploads_dir.iterdir())
    content = path.read_bytes()

    def fail_delete(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("DELETE FROM documents"):
            raise IntegrityError("injected delete failure", {}, Exception("test"))

    event.listen(auth_database.engine, "before_cursor_execute", fail_delete)
    try:
        response = auth_client.delete(f"/api/documents/{original.id}")
    finally:
        event.remove(auth_database.engine, "before_cursor_execute", fail_delete)
    assert response.status_code == 503
    assert path.read_bytes() == content
    assert auth_client.get(f"/api/documents/{original.id}").json()["status"] == "ready"


def test_corrupt_or_incompatible_ready_indexes_raise_explicit_errors(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
    auth_database: Database,
    embedding_stub: ControlledEmbedder,
) -> None:
    ready(auth_client, indexer, upload(auth_client))
    with auth_database.session_factory() as db:
        with pytest.raises(IndexReadError, match="model changed"):
            load_ready_chunks(db, registered_owner.organization.id, "other-model")
        chunk = db.scalar(select(Chunk))
        assert chunk is not None
        chunk.embedding = b"bad"
        db.commit()
        with pytest.raises(IndexReadError, match="incomplete index"):
            load_ready_chunks(db, registered_owner.organization.id, embedding_stub.model_name)


def test_document_routes_describe_multipart_without_automatic_body_parsing(
    auth_client: TestClient,
) -> None:
    schema = auth_client.get("/openapi.json").json()
    for path, method in (("/api/documents", "post"), ("/api/documents/{document_id}", "put")):
        content = schema["paths"][path][method]["requestBody"]["content"]
        assert content["multipart/form-data"]["schema"]["properties"]["file"]["format"] == "binary"


@pytest.mark.parametrize(
    "output",
    [
        np.array([[1, 2]], dtype=np.float32),
        np.zeros((1, 4), dtype=np.float32),
        np.array([[1, 2, np.nan, 4]], dtype=np.float32),
    ],
)
def test_invalid_model_vectors_never_produce_a_ready_document(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
    embedding_stub: ControlledEmbedder,
    auth_database: Database,
    output,
) -> None:
    embedding_stub.output = output
    response = upload(auth_client)
    assert response.status_code == 202 and indexer.wait_until_idle(timeout=5)
    assert auth_client.get(f"/api/documents/{response.json()['id']}").json()["status"] == "failed"
    with auth_database.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Chunk)) == 0


def test_failed_index_state_is_retried_without_returning_stuck_processing(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
    embedding_stub: ControlledEmbedder,
    auth_database: Database,
) -> None:
    embedding_stub.failure = RuntimeError("test model failure")
    unavailable = True

    def fail_updates(connection, cursor, statement, parameters, context, executemany):
        if unavailable and statement.startswith("UPDATE documents"):
            raise OperationalError("injected update outage", {}, Exception("test"))

    event.listen(auth_database.engine, "before_cursor_execute", fail_updates)
    try:
        response = upload(auth_client)
        assert response.status_code == 202 and indexer.wait_until_idle(timeout=5)
        assert auth_client.get("/api/documents").status_code == 503
        unavailable = False
        result = auth_client.get("/api/documents")
        assert result.status_code == 200
        assert result.json()["documents"][0]["status"] == "failed"
    finally:
        event.remove(auth_database.engine, "before_cursor_execute", fail_updates)


def test_replacement_database_failure_restores_the_old_version(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
    auth_database: Database,
    auth_settings: Settings,
    embedding_stub: ControlledEmbedder,
) -> None:
    original = ready(auth_client, indexer, upload(auth_client))
    path = next(auth_settings.uploads_dir.iterdir())
    content = path.read_bytes()

    def fail_chunks(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO chunks"):
            raise IntegrityError("injected replacement insert failure", {}, Exception("test"))

    event.listen(auth_database.engine, "before_cursor_execute", fail_chunks)
    try:
        response = auth_client.put(
            f"/api/documents/{original.id}",
            files={"file": ("new.pdf", make_pdf("NEW"), "application/pdf")},
        )
        assert response.status_code == 202 and indexer.wait_until_idle(timeout=5)
    finally:
        event.remove(auth_database.engine, "before_cursor_execute", fail_chunks)
    current = auth_client.get(f"/api/documents/{original.id}").json()
    assert current["status"] == "ready" and current["replacement"]["status"] == "failed"
    assert path.read_bytes() == content
    assert len(list(auth_settings.uploads_dir.iterdir())) == 1
    with auth_database.session_factory() as db:
        assert (
            "Original policy."
            in load_ready_chunks(db, registered_owner.organization.id, embedding_stub.model_name)[
                0
            ].text
        )


def test_interrupted_jobs_are_recovered_without_discarding_a_ready_version(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    indexer: IndexingService,
    auth_database: Database,
    embedding_stub: ControlledEmbedder,
) -> None:
    original = ready(auth_client, indexer, upload(auth_client))
    pending_key = indexer.storage.create(make_pdf("Pending replacement"))
    unfinished_key = indexer.storage.create(make_pdf("Unfinished upload"))
    unfinished_id = str(uuid4())
    with auth_database.session_factory() as db:
        previous = db.get(Document, original.id)
        assert previous is not None
        previous.pending_revision = uuid4().hex
        previous.pending_storage_key = pending_key
        previous.replacement_name = "pending.pdf"
        db.add(
            Document(
                id=unfinished_id,
                org_id=registered_owner.organization.id,
                name="unfinished.pdf",
                pages=1,
                size_bytes=100,
                storage_key=unfinished_key,
                revision=uuid4().hex,
                status="processing",
                warnings=[],
                chunk_count=0,
            )
        )
        db.flush()
        db.add(
            Chunk(
                id=str(uuid4()),
                document_id=unfinished_id,
                org_id=registered_owner.organization.id,
                ordinal=0,
                page=1,
                text="Partial content must not survive.",
                embedding=np.ones(4, dtype="<f4").tobytes(),
            )
        )
        db.commit()
    indexer.recover_interrupted()
    current = auth_client.get(f"/api/documents/{original.id}").json()
    assert current["status"] == "ready"
    assert current["replacement"]["error"]["code"] == "processing_interrupted"
    failed = auth_client.get(f"/api/documents/{unfinished_id}").json()
    assert failed["status"] == "failed" and failed["error"]["code"] == "processing_interrupted"
    assert not indexer.storage.path(pending_key).exists()
    assert indexer.storage.path(unfinished_key).exists()
    with auth_database.session_factory() as db:
        chunks = load_ready_chunks(db, registered_owner.organization.id, embedding_stub.model_name)
        assert len(chunks) == 1 and "Original policy." in chunks[0].text
        assert db.scalar(select(func.count()).select_from(Chunk)) == 1


def test_index_queue_is_bounded_and_slots_are_reusable(
    auth_client: TestClient,
    second_auth_client: TestClient,
    registered_owner: SessionSummary,
    auth_app: FastAPI,
    indexer: IndexingService,
    embedding_stub: ControlledEmbedder,
) -> None:
    assert (
        second_auth_client.post(
            "/api/auth/register",
            json={
                "organization_name": "Queue B",
                "full_name": "Queue Owner B",
                "email": "queue-b@example.com",
                "password": "Queue test password 123!",
            },
        ).status_code
        == 201
    )
    third = TestClient(auth_app, headers={"Origin": "http://127.0.0.1:5173"})
    try:
        assert (
            third.post(
                "/api/auth/register",
                json={
                    "organization_name": "Queue C",
                    "full_name": "Queue Owner C",
                    "email": "queue-c@example.com",
                    "password": "Queue test password 123!",
                },
            ).status_code
            == 201
        )
        embedding_stub.release.clear()
        try:
            for client in (auth_client, second_auth_client):
                for number in range(10):
                    assert upload(client, f"queued-{number}.pdf").status_code == 202
            rejected = upload(third)
            assert rejected.status_code == 503
            assert rejected.json()["error"]["code"] == "processing_busy"
            assert third.get("/api/documents").json()["used"] == 0
        finally:
            embedding_stub.release.set()
        assert indexer.wait_until_idle(timeout=5)
        ready(third, indexer, upload(third))
    finally:
        third.close()
