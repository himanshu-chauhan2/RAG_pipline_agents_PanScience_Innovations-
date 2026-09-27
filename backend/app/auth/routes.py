import logging
import secrets
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.dependencies import (
    CurrentPrincipal,
    DbSession,
    get_auth_state,
    get_settings,
    require_auth_origin,
)
from app.auth.schemas import (
    AuthInput,
    OrganizationSummary,
    RegisterInput,
    SessionSummary,
    UserSummary,
)
from app.auth.security import AuthState, hash_password, issue_session_token, verify_password
from app.config import SESSION_COOKIE_NAME, Settings
from app.errors import ApiError
from app.models import Assistant, AuthSession, Organization, User, unix_time

router = APIRouter(prefix="/api/auth", tags=["accounts"])
organization_router = APIRouter(prefix="/api/organizations", tags=["organizations"])
Configuration = Annotated[Settings, Depends(get_settings)]
Authentication = Annotated[AuthState, Depends(get_auth_state)]
logger = logging.getLogger(__name__)


def summarize(user: User, organization: Organization, session: AuthSession) -> SessionSummary:
    return SessionSummary(
        user=UserSummary(id=user.id, full_name=user.full_name, email=user.email),
        organization=OrganizationSummary(id=organization.id, name=organization.name),
        expires_at=datetime.fromtimestamp(session.expires_at, UTC),
    )


def new_session(user: User, settings: Settings) -> AuthSession:
    now = unix_time()
    return AuthSession(
        id=str(uuid4()),
        user_id=user.id,
        created_at=now,
        expires_at=now + settings.auth_session_minutes * 60,
    )


def set_session_cookie(
    response: Response, token: str, session: AuthSession, settings: Settings
) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=settings.auth_session_minutes * 60,
        expires=datetime.fromtimestamp(session.expires_at, UTC),
        path="/api",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.post(
    "/register",
    response_model=SessionSummary,
    status_code=201,
    dependencies=[Depends(require_auth_origin)],
)
def register(
    payload: RegisterInput,
    response: Response,
    db: DbSession,
    settings: Configuration,
    auth: Authentication,
) -> SessionSummary:
    if db.scalar(select(User.id).where(User.email == payload.email)) is not None:
        raise ApiError(
            409,
            "email_registered",
            "An account with this email already exists.",
            {"email": "Use another email or sign in to the existing account."},
        )
    organization = Organization(id=str(uuid4()), name=payload.organization_name)
    user = User(
        id=str(uuid4()),
        org_id=organization.id,
        full_name=payload.full_name,
        email=payload.email,
        password_hash=hash_password(payload.password.get_secret_value()),
    )
    assistant = Assistant(id=str(uuid4()), org_id=organization.id, token=secrets.token_urlsafe(32))
    session = new_session(user, settings)
    token = issue_session_token(user, session, auth.signing_key)
    try:
        db.add(organization)
        db.flush()
        db.add(user)
        db.flush()
        db.add_all([assistant, session])
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.scalar(select(User.id).where(User.email == payload.email)) is not None:
            raise ApiError(
                409,
                "email_registered",
                "An account with this email already exists.",
                {"email": "Use another email or sign in to the existing account."},
            ) from None
        raise
    set_session_cookie(response, token, session, settings)
    return summarize(user, organization, session)


@router.post("/login", response_model=SessionSummary, dependencies=[Depends(require_auth_origin)])
def login(
    payload: AuthInput,
    request: Request,
    response: Response,
    db: DbSession,
    settings: Configuration,
    auth: Authentication,
) -> SessionSummary:
    row = db.execute(
        select(User, Organization)
        .join(Organization, User.org_id == Organization.id)
        .where(User.email == payload.email)
    ).one_or_none()
    password_hash = auth.dummy_password_hash if row is None else row[0].password_hash
    try:
        password_matches = verify_password(payload.password.get_secret_value(), password_hash)
    except (ValueError, UnicodeError):
        logger.error("Invalid stored password hash request_id=%s", request.state.request_id)
        raise ApiError(
            503, "authentication_unavailable", "Sign-in is temporarily unavailable. Try again."
        ) from None
    if row is None or not password_matches:
        raise ApiError(401, "invalid_credentials", "The email or password is incorrect.")
    user, organization = row
    session = new_session(user, settings)
    token = issue_session_token(user, session, auth.signing_key)
    db.add(session)
    db.commit()
    set_session_cookie(response, token, session, settings)
    return summarize(user, organization, session)


@router.get("/me", response_model=SessionSummary)
def current_account(principal: CurrentPrincipal) -> SessionSummary:
    return summarize(principal.user, principal.organization, principal.session)


@router.post("/logout", status_code=204, dependencies=[Depends(require_auth_origin)])
def logout(principal: CurrentPrincipal, db: DbSession, settings: Configuration) -> Response:
    principal.session.revoked_at = unix_time()
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/api",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@organization_router.get("/{organization_id}", response_model=OrganizationSummary)
def get_organization(
    organization_id: UUID, principal: CurrentPrincipal, db: DbSession
) -> OrganizationSummary:
    organization = db.scalar(
        select(Organization).where(
            Organization.id == str(organization_id),
            Organization.id == principal.organization.id,
        )
    )
    if organization is None:
        raise ApiError(404, "organization_not_found", "Organisation not found.")
    return OrganizationSummary(id=organization.id, name=organization.name)
