from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from app.kb.limits import MAX_DOCUMENTS, MAX_PDF_BYTES, MAX_PDF_PAGES
from app.models import Document


class DocumentError(BaseModel):
    code: str
    message: str


class ReplacementSummary(BaseModel):
    name: str
    status: Literal["processing", "failed"]
    error: DocumentError | None


class DocumentSummary(BaseModel):
    id: str
    name: str
    pages: int
    size_bytes: int
    status: Literal["processing", "ready", "failed"]
    error: DocumentError | None
    warnings: list[str]
    chunk_count: int
    created_at: datetime
    updated_at: datetime
    replacement: ReplacementSummary | None


class DocumentList(BaseModel):
    documents: list[DocumentSummary]
    used: int
    max_documents: int = MAX_DOCUMENTS
    max_pages: int = MAX_PDF_PAGES
    max_size_bytes: int = MAX_PDF_BYTES


def stored_error(code: str | None, message: str | None) -> DocumentError | None:
    if code is None and message is None:
        return None
    if not code or not message:
        raise RuntimeError("Stored document error metadata is incomplete.")
    return DocumentError(code=code, message=message)


def summarize_document(document: Document) -> DocumentSummary:
    replacement = None
    if document.pending_revision or document.replacement_error_code:
        if document.replacement_name is None:
            raise RuntimeError("Stored replacement metadata is incomplete.")
        replacement = ReplacementSummary(
            name=document.replacement_name,
            status="processing" if document.pending_revision else "failed",
            error=stored_error(document.replacement_error_code, document.replacement_error_message),
        )
    return DocumentSummary.model_validate(
        {
            "id": document.id,
            "name": document.name,
            "pages": document.pages,
            "size_bytes": document.size_bytes,
            "status": document.status,
            "error": stored_error(document.error_code, document.error_message),
            "warnings": document.warnings,
            "chunk_count": document.chunk_count,
            "created_at": datetime.fromtimestamp(document.created_at, UTC),
            "updated_at": datetime.fromtimestamp(document.updated_at, UTC),
            "replacement": replacement,
        }
    )
