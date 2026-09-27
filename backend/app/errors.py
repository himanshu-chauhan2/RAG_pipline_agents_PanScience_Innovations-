import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.config import SESSION_COOKIE_NAME, Settings

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str, fields: dict[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields


def error_response(request: Request, error: ApiError) -> JSONResponse:
    details: dict[str, object] = {
        "code": error.code,
        "message": error.message,
        "request_id": request.state.request_id,
    }
    if error.fields:
        details["fields"] = error.fields
    return JSONResponse(status_code=error.status, content={"error": details})


def install_error_handlers(application: FastAPI, settings: Settings) -> None:
    @application.middleware("http")
    async def request_metadata(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        logger.info(
            "API request rejected code=%s status=%s request_id=%s",
            error.code,
            error.status,
            request.state.request_id,
        )
        response = error_response(request, error)
        if error.code == "unauthenticated":
            response.delete_cookie(
                SESSION_COOKIE_NAME,
                path="/api",
                secure=settings.auth_cookie_secure,
                httponly=True,
                samesite="lax",
            )
        return response

    @application.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error: RequestValidationError) -> JSONResponse:
        fields: dict[str, str] = {}
        for issue in error.errors():
            location = [str(part) for part in issue["loc"] if part != "body"]
            field = ".".join(location) or "request"
            fields.setdefault(field, issue["msg"])
        logger.info("Request validation failed request_id=%s", request.state.request_id)
        return error_response(
            request, ApiError(400, "invalid_input", "Please check the highlighted fields.", fields)
        )

    @application.exception_handler(SQLAlchemyError)
    async def storage_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
        logger.error(
            "Database operation failed request_id=%s", request.state.request_id, exc_info=error
        )
        return error_response(
            request,
            ApiError(
                503, "storage_unavailable", "The workspace database is unavailable. Try again."
            ),
        )
