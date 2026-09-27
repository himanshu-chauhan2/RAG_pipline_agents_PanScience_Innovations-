from conftest import make_pdf, pad_pdf
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth.schemas import SessionSummary
from app.config import Settings
from app.db import Database
from app.kb.limits import MAX_MULTIPART_BYTES, MAX_PDF_BYTES
from app.models import Document


def test_unauthenticated_upload_is_rejected_before_body_parsing(
    auth_client: TestClient,
    auth_database: Database,
) -> None:
    response = auth_client.post(
        "/api/documents", content=b"not multipart", headers={"Content-Type": "multipart/form-data"}
    )
    assert response.status_code == 401
    with auth_database.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 0


def test_upload_origin_is_checked_before_parsing(
    auth_client: TestClient,
    registered_owner: SessionSummary,
) -> None:
    response = auth_client.post(
        "/api/documents",
        content=b"bad",
        headers={"Origin": "https://untrusted.example", "Content-Type": "multipart/form-data"},
    )
    assert response.status_code == 403


def test_exact_file_byte_boundary_through_multipart(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    auth_settings: Settings,
) -> None:
    content = pad_pdf(make_pdf(), MAX_PDF_BYTES)
    allowed = auth_client.post(
        "/api/documents", files={"file": ("max.pdf", content, "application/pdf")}
    )
    assert allowed.status_code == 202
    assert allowed.json()["size_bytes"] == MAX_PDF_BYTES
    rejected = auth_client.post(
        "/api/documents", files={"file": ("over.pdf", content + b" ", "application/pdf")}
    )
    assert rejected.status_code == 413
    assert rejected.json()["error"]["code"] == "file_too_large"
    assert auth_client.get("/api/documents").json()["used"] == 1
    assert len(list(auth_settings.uploads_dir.iterdir())) == 1


def test_exact_page_boundary_through_multipart(
    auth_client: TestClient,
    registered_owner: SessionSummary,
) -> None:
    accepted = auth_client.post(
        "/api/documents", files={"file": ("twenty.pdf", make_pdf(pages=20), "application/pdf")}
    )
    assert accepted.status_code == 202 and accepted.json()["pages"] == 20
    rejected = auth_client.post(
        "/api/documents", files={"file": ("twenty-one.pdf", make_pdf(pages=21), "application/pdf")}
    )
    assert rejected.status_code == 400 and rejected.json()["error"]["code"] == "page_limit"
    assert auth_client.get("/api/documents").json()["used"] == 1


def test_extra_fields_and_multiple_files_cannot_bypass_the_upload_contract(
    auth_client: TestClient,
    registered_owner: SessionSummary,
) -> None:
    responses = [
        auth_client.post(
            "/api/documents",
            data={"org_id": "another-tenant"},
            files={"file": ("policy.pdf", make_pdf(), "application/pdf")},
        ),
        auth_client.post(
            "/api/documents",
            files=[("file", ("a.pdf", make_pdf())), ("file", ("b.pdf", make_pdf()))],
        ),
        auth_client.post(
            "/api/documents",
            files={"wrong": ("policy.pdf", make_pdf(), "application/pdf")},
        ),
        auth_client.post("/api/documents", json={"file": "not a PDF upload"}),
    ]
    assert all(response.status_code == 400 for response in responses)
    assert auth_client.get("/api/documents").json()["used"] == 0


def test_malformed_multipart_has_a_meaningful_error(
    auth_client: TestClient,
    registered_owner: SessionSummary,
) -> None:
    response = auth_client.post(
        "/api/documents",
        content=b"bad multipart body",
        headers={"Content-Type": "multipart/form-data; boundary=boundary"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_upload"


def test_stream_limit_does_not_trust_missing_content_length(
    auth_client: TestClient,
    registered_owner: SessionSummary,
) -> None:
    def oversized_body():
        for _ in range(MAX_MULTIPART_BYTES // 100_000 + 2):
            yield b"x" * 100_000

    response = auth_client.post(
        "/api/documents",
        content=oversized_body(),
        headers={"Content-Type": "multipart/form-data; boundary=boundary"},
    )
    assert response.status_code == 413
    assert auth_client.get("/api/documents").json()["used"] == 0
