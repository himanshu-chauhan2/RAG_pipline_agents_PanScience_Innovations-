from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from app import __version__
from app.auth.routes import organization_router
from app.auth.routes import router as auth_router
from app.auth.security import initialize_auth
from app.config import Settings
from app.db import Database
from app.errors import install_error_handlers
from app.kb.embeddings import Embedder, LocalEmbedder
from app.kb.routes import router as document_router
from app.kb.service import IndexingService
from app.kb.storage import PrivateStorage


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["knowledge-decision-assistant"] = "knowledge-decision-assistant"
    version: str = __version__
    phase: Literal["P2"] = "P2"
    gateway_configured: bool


def create_app(settings: Settings | None = None, *, embedder: Embedder | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database = Database(configuration.database_path)
        indexer: IndexingService | None = None
        try:
            database.initialize()
            application.state.database = database
            application.state.auth = initialize_auth(configuration)
            indexer = IndexingService(
                database,
                PrivateStorage(configuration.uploads_dir),
                embedder if embedder is not None else LocalEmbedder(configuration),
            )
            indexer.recover_interrupted()
            application.state.indexer = indexer
            yield
        finally:
            if indexer is not None:
                indexer.close()
            database.close()

    application = FastAPI(
        title="AI Knowledge & Decision Assistant",
        version=__version__,
        description=(
            "P2 organisation accounts and private PDF knowledge-base management. "
            "Question answering is not implemented yet."
        ),
        lifespan=lifespan,
    )
    application.state.settings = configuration
    install_error_handlers(application, configuration)
    application.include_router(auth_router)
    application.include_router(organization_router)
    application.include_router(document_router)

    @application.get("/api/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse(gateway_configured=configuration.gateway_configured)

    return application


app = create_app()
