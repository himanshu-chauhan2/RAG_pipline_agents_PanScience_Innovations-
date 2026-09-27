from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from jwt import InvalidTokenError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import AuthState, decode_session_token
from app.config import SESSION_COOKIE_NAME, Settings
from app.db import get_session
from app.errors import ApiError
from app.models import AuthSession, Organization, User, unix_time

DbSession = Annotated[Session, Depends(get_session)]


@dataclass(frozen=True)
class Principal:
    user: User
    organization: Organization
    session: AuthSession


def get_settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise RuntimeError("Application configuration has not been initialized")
    return settings


def get_auth_state(request: Request) -> AuthState:
    state = request.app.state.auth
    if not isinstance(state, AuthState):
        raise RuntimeError("Application authentication has not been initialized")
    return state


def require_auth_origin(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    if request.headers.get("origin") not in settings.auth_allowed_origins:
        raise ApiError(
            403, "origin_not_allowed", "This origin is not allowed to change an account session."
        )


def require_principal(
    request: Request, db: DbSession, auth: Annotated[AuthState, Depends(get_auth_state)]
) -> Principal:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise ApiError(401, "unauthenticated", "Sign in to access your organisation.")
    try:
        claims = decode_session_token(token, auth.signing_key)
    except (InvalidTokenError, ValidationError):
        raise ApiError(
            401, "unauthenticated", "Your session is invalid or expired. Sign in again."
        ) from None
    row = db.execute(
        select(User, Organization, AuthSession)
        .join(Organization, User.org_id == Organization.id)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(
            User.id == str(claims.sub),
            Organization.id == str(claims.org_id),
            AuthSession.id == str(claims.sid),
            AuthSession.expires_at > unix_time(),
            AuthSession.revoked_at.is_(None),
        )
    ).one_or_none()
    if row is None:
        raise ApiError(401, "unauthenticated", "Your session is invalid or expired. Sign in again.")
    user, organization, session = row
    return Principal(user=user, organization=organization, session=session)


CurrentPrincipal = Annotated[Principal, Depends(require_principal)]
