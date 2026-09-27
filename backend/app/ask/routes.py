from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.ask.schemas import AskRequest, AskResponse
from app.ask.service import AskService
from app.auth.dependencies import DbSession, Principal
from app.errors import ApiError
from app.kb.routes import require_workspace
from app.models import Assistant

OwnerPrincipal = Annotated[Principal, Depends(require_workspace)]

router = APIRouter(prefix="/api", tags=["ask"])


class AssistantLink(BaseModel):
    organization_id: str
    organization_name: str
    token: str
    public_path: str
    ask_endpoint: str = "/api/ask"


@router.get("/assistant", response_model=AssistantLink)
def get_assistant(principal: OwnerPrincipal, db: DbSession) -> AssistantLink:
    token = db.scalar(select(Assistant.token).where(Assistant.org_id == principal.organization.id))
    if token is None:
        raise ApiError(404, "assistant_not_found", "This organisation has no assistant link.")
    return AssistantLink(
        organization_id=principal.organization.id,
        organization_name=principal.organization.name,
        token=token,
        public_path=f"/a/{quote(token, safe='')}",
    )


@router.post("/ask", response_model=AskResponse)
async def ask(payload: AskRequest, request: Request) -> AskResponse:
    service = getattr(request.app.state, "ask_service", None)
    if not isinstance(service, AskService):
        raise ApiError(503, "service_unavailable", "The assistant is still starting. Try again.")
    return await service.ask(payload)
