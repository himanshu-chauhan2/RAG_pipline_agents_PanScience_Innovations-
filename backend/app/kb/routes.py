from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from app.auth.dependencies import CurrentPrincipal, Principal, require_auth_origin
from app.errors import ApiError
from app.kb.pdf import prepare_pdf
from app.kb.schemas import DocumentList, DocumentSummary
from app.kb.service import IndexingService
from app.kb.uploads import read_pdf_upload

router = APIRouter(prefix="/api/documents", tags=["knowledge base"])
UPLOAD_SCHEMA = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "additionalProperties": False,
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


def get_indexer(request: Request) -> IndexingService:
    service = request.app.state.indexer
    if not isinstance(service, IndexingService):
        raise RuntimeError("The document indexer has not been initialized.")
    return service


Indexer = Annotated[IndexingService, Depends(get_indexer)]


def require_workspace(request: Request, principal: CurrentPrincipal) -> Principal:
    expected = request.headers.get("x-organization-id")
    if expected is not None and expected != principal.organization.id:
        raise ApiError(
            409,
            "workspace_changed",
            "The active organisation changed. Refresh your workspace before retrying.",
        )
    return principal


DocumentPrincipal = Annotated[Principal, Depends(require_workspace)]


@router.get("", response_model=DocumentList)
def list_documents(principal: DocumentPrincipal, service: Indexer) -> DocumentList:
    return service.list_documents(principal.organization.id)


@router.get("/{document_id}", response_model=DocumentSummary)
def get_document(
    document_id: UUID, principal: DocumentPrincipal, service: Indexer
) -> DocumentSummary:
    return service.get_document(principal.organization.id, str(document_id))


async def accept_upload(
    request: Request, service: IndexingService, org_id: str, replace_id: str | None = None
) -> DocumentSummary:
    if not service.upload_slots.acquire(blocking=False):
        raise ApiError(
            503, "processing_busy", "Other uploads are being validated. Try again shortly."
        )
    try:
        if replace_id is not None:
            await run_in_threadpool(service.check_replacement, org_id, replace_id)
        filename, content = await read_pdf_upload(request)
        pdf = await run_in_threadpool(prepare_pdf, filename, content)
        if await request.is_disconnected():
            raise ApiError(499, "upload_cancelled", "The upload was cancelled before indexing.")
        return await run_in_threadpool(service.add_document, org_id, pdf, replace_id)
    finally:
        service.upload_slots.release()


@router.post(
    "",
    response_model=DocumentSummary,
    status_code=202,
    dependencies=[Depends(require_auth_origin)],
    openapi_extra=UPLOAD_SCHEMA,
)
async def upload_document(
    request: Request, principal: DocumentPrincipal, service: Indexer
) -> DocumentSummary:
    return await accept_upload(request, service, principal.organization.id)


@router.put(
    "/{document_id}",
    response_model=DocumentSummary,
    status_code=202,
    dependencies=[Depends(require_auth_origin)],
    openapi_extra=UPLOAD_SCHEMA,
)
async def replace_document(
    document_id: UUID, request: Request, principal: DocumentPrincipal, service: Indexer
) -> DocumentSummary:
    return await accept_upload(request, service, principal.organization.id, str(document_id))


@router.delete("/{document_id}", status_code=204, dependencies=[Depends(require_auth_origin)])
def delete_document(document_id: UUID, principal: DocumentPrincipal, service: Indexer) -> Response:
    service.delete_document(principal.organization.id, str(document_id))
    return Response(status_code=204)
