import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

import bcrypt
import jwt
from pydantic import BaseModel, ConfigDict, SecretStr

from app.config import Settings
from app.models import AuthSession, User

PASSWORD_ROUNDS = 12
TOKEN_ISSUER = "knowledge-decision-assistant"
TOKEN_AUDIENCE = "admin-dashboard"


@dataclass(frozen=True)
class AuthState:
    signing_key: SecretStr
    dummy_password_hash: str


class AdminClaims(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub: UUID
    org_id: UUID
    sid: UUID
    token_type: Literal["admin"]
    iss: Literal["knowledge-decision-assistant"]
    aud: Literal["admin-dashboard"]
    exp: int
    iat: int
    nbf: int


def read_signing_key(path: Path) -> SecretStr:
    key = path.read_text(encoding="utf-8").strip()
    if len(key.encode("utf-8")) < 32:
        raise RuntimeError(
            "The local auth signing key is invalid. Set AUTH_SECRET_KEY or replace the key file."
        )
    return SecretStr(key)


def load_signing_key(settings: Settings) -> SecretStr:
    if settings.auth_secret_key.get_secret_value():
        return settings.auth_secret_key
    path = settings.auth_secret_file
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as output:
            output.write(secrets.token_urlsafe(48))
    except FileExistsError:
        return read_signing_key(path)
    return read_signing_key(path)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=PASSWORD_ROUNDS)).decode(
        "ascii"
    )


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))


def initialize_auth(settings: Settings) -> AuthState:
    return AuthState(
        signing_key=load_signing_key(settings),
        dummy_password_hash=hash_password(secrets.token_urlsafe(24)),
    )


def issue_session_token(user: User, session: AuthSession, signing_key: SecretStr) -> str:
    now = session.created_at
    return jwt.encode(
        {
            "sub": user.id,
            "org_id": user.org_id,
            "sid": session.id,
            "token_type": "admin",
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "iat": now,
            "nbf": now,
            "exp": session.expires_at,
        },
        signing_key.get_secret_value(),
        algorithm="HS256",
    )


def decode_session_token(token: str, signing_key: SecretStr) -> AdminClaims:
    payload = jwt.decode(
        token,
        signing_key.get_secret_value(),
        algorithms=["HS256"],
        issuer=TOKEN_ISSUER,
        audience=TOKEN_AUDIENCE,
        options={
            "require": ["sub", "org_id", "sid", "token_type", "iss", "aud", "iat", "nbf", "exp"]
        },
    )
    return AdminClaims.model_validate(payload)
