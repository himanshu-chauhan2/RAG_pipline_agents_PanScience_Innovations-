from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from app import __version__
from app.config import Settings


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["knowledge-decision-assistant"] = "knowledge-decision-assistant"
    version: str = __version__
    phase: Literal["P0"] = "P0"
    gateway_configured: bool


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()
    application = FastAPI(
        title="AI Knowledge & Decision Assistant",
        version=__version__,
        description=(
            "P0 foundation. Accounts, document ingestion and question answering follow later."
        ),
    )

    @application.get("/api/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse(gateway_configured=configuration.gateway_configured)

    return application


app = create_app()
