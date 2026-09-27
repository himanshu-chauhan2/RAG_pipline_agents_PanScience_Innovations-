from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import UUID

import jwt
import pytest
from app.auth.schemas import SessionSummary
from app.auth.security import (
    decode_session_token,
    load_signing_key,
    verify_password,
)
from app.config import SESSION_COOKIE_NAME, Settings
from app.db import Database
from app.main import create_app
from app.models import Assistant, AuthSession, Organization, User, unix_time
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError


def test_registration_creates_an_atomic_private_workspace(
    auth_client: TestClient,
    auth_database: Database,
    registration_payload: dict[str, str],
) -> None:
    response = auth_client.post("/api/auth/register", json=registration_payload)
    assert response.status_code == 201
    result = SessionSummary.model_validate(response.json())
    assert set(response.json()) == {"user", "organization", "expires_at"}
    assert result.user.full_name == "Alex Owner"
    assert result.organization.name == "Northbridge Test"
    assert result.expires_at > datetime.now(UTC)
    with auth_database.session_factory() as db:
        for model in (Organization, User, Assistant, AuthSession):
            assert db.scalar(select(func.count()).select_from(model)) == 1
        user = db.get(User, result.user.id)
        assistant = db.scalar(select(Assistant))
        assert user is not None and assistant is not None
        assert user.password_hash != registration_payload["password"]
        assert verify_password(registration_payload["password"], user.password_hash)
        assert assistant.org_id == result.organization.id
        assert len(assistant.token) >= 43
        assert assistant.token not in response.text
        assert user.password_hash not in response.text
    assert registration_payload["password"] not in response.text
    assert response.headers["cache-control"] == "no-store"
    UUID(response.headers["x-request-id"])


def test_cookie_and_claims_are_scoped_to_admin_sessions(
    auth_client: TestClient,
    auth_settings: Settings,
    registered_owner: SessionSummary,
) -> None:
    response = auth_client.post(
        "/api/auth/login", json={"email": "alex@example.com", "password": "Correct horse 123!"}
    )
    assert response.status_code == 200
    header = response.headers["set-cookie"]
    assert "HttpOnly" in header and "SameSite=lax" in header and "Path=/api" in header
    assert "Max-Age=28800" in header
    token = auth_client.cookies.get(SESSION_COOKIE_NAME)
    assert token is not None
    claims = decode_session_token(token, auth_settings.auth_secret_key)
    assert str(claims.sub) == registered_owner.user.id
    assert str(claims.org_id) == registered_owner.organization.id
    assert claims.token_type == "admin"
    assert claims.exp - claims.iat == 8 * 60 * 60
    assert "token" not in response.json()


def test_registration_trims_names_and_normalizes_email(
    auth_client: TestClient,
    registration_payload: dict[str, str],
) -> None:
    response = auth_client.post(
        "/api/auth/register",
        json={
            **registration_payload,
            "organization_name": "  Example Company  ",
            "full_name": "  Alex Owner  ",
            "email": "  ALEX@EXAMPLE.COM  ",
        },
    )
    assert response.status_code == 201
    assert response.json()["organization"]["name"] == "Example Company"
    assert response.json()["user"]["full_name"] == "Alex Owner"
    assert response.json()["user"]["email"] == "alex@example.com"


def test_current_account_is_loaded_from_the_authenticated_session(
    auth_client: TestClient,
    registered_owner: SessionSummary,
) -> None:
    response = auth_client.get("/api/auth/me")
    assert response.status_code == 200
    assert SessionSummary.model_validate(response.json()) == registered_owner


def test_duplicate_email_is_rejected_without_orphan_records(
    auth_client: TestClient,
    auth_database: Database,
    registered_owner: SessionSummary,
    registration_payload: dict[str, str],
) -> None:
    response = auth_client.post(
        "/api/auth/register",
        json={
            **registration_payload,
            "email": "ALEX@EXAMPLE.COM",
            "organization_name": "Other Company",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_registered"
    with auth_database.session_factory() as db:
        for model in (Organization, User, Assistant, AuthSession):
            assert db.scalar(select(func.count()).select_from(model)) == 1


def test_concurrent_registration_has_one_winner_and_no_orphans(
    auth_client: TestClient,
    second_auth_client: TestClient,
    auth_database: Database,
    registration_payload: dict[str, str],
) -> None:
    ready = Barrier(2)

    def attempt(client: TestClient) -> int:
        ready.wait(timeout=5)
        return client.post("/api/auth/register", json=registration_payload).status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        statuses = list(workers.map(attempt, [auth_client, second_auth_client]))
    assert sorted(statuses) == [201, 409]
    with auth_database.session_factory() as db:
        for model in (Organization, User, Assistant, AuthSession):
            assert db.scalar(select(func.count()).select_from(model)) == 1


@pytest.mark.parametrize("password", ["x" * 72, "€" * 24])
def test_password_exact_byte_limit_is_accepted(
    auth_client: TestClient,
    registration_payload: dict[str, str],
    password: str,
) -> None:
    response = auth_client.post(
        "/api/auth/register", json={**registration_payload, "password": password}
    )
    assert response.status_code == 201


@pytest.mark.parametrize("password", ["x" * 73, "€" * 25, "short", " " * 8, "abcd\x00efgh"])
def test_invalid_passwords_have_safe_field_errors(
    auth_client: TestClient,
    registration_payload: dict[str, str],
    password: str,
) -> None:
    response = auth_client.post(
        "/api/auth/register", json={**registration_payload, "password": password}
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_input"
    assert "password" in error["fields"]
    assert password not in response.text
    assert "input" not in error["fields"]
    assert error["request_id"] == response.headers["x-request-id"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("organization_name", "  "),
        ("organization_name", "x" * 121),
        ("full_name", ""),
        ("full_name", "x" * 101),
        ("email", "not-an-email"),
    ],
)
def test_registration_validates_account_fields(
    auth_client: TestClient,
    registration_payload: dict[str, str],
    field: str,
    value: str,
) -> None:
    response = auth_client.post("/api/auth/register", json={**registration_payload, field: value})
    assert response.status_code == 400
    assert field in response.json()["error"]["fields"]


def test_client_cannot_choose_an_organization_or_role(
    auth_client: TestClient,
    registration_payload: dict[str, str],
    auth_database: Database,
) -> None:
    response = auth_client.post(
        "/api/auth/register", json={**registration_payload, "org_id": "other", "role": "superuser"}
    )
    assert response.status_code == 400
    with auth_database.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Organization)) == 0


def test_password_whitespace_is_preserved(
    auth_client: TestClient,
    registration_payload: dict[str, str],
) -> None:
    password = "  space preserving password  "
    assert (
        auth_client.post(
            "/api/auth/register", json={**registration_payload, "password": password}
        ).status_code
        == 201
    )
    assert auth_client.post("/api/auth/logout").status_code == 204
    assert (
        auth_client.post(
            "/api/auth/login",
            json={"email": registration_payload["email"], "password": password.strip()},
        ).status_code
        == 401
    )
    assert (
        auth_client.post(
            "/api/auth/login", json={"email": registration_payload["email"], "password": password}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("email", ["alex@example.com", "missing@example.com"])
def test_wrong_password_and_unknown_email_have_the_same_error(
    second_auth_client: TestClient,
    registered_owner: SessionSummary,
    email: str,
) -> None:
    response = second_auth_client.post(
        "/api/auth/login", json={"email": email, "password": "wrong"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert response.json()["error"]["message"] == "The email or password is incorrect."
    assert SESSION_COOKIE_NAME not in second_auth_client.cookies


def test_logout_revokes_the_session_even_if_the_cookie_is_replayed(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    auth_database: Database,
) -> None:
    token = auth_client.cookies.get(SESSION_COOKIE_NAME)
    assert token is not None
    assert auth_client.post("/api/auth/logout").status_code == 204
    assert SESSION_COOKIE_NAME not in auth_client.cookies
    assert auth_client.get("/api/auth/me").status_code == 401
    replay = auth_client.get("/api/auth/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"})
    assert replay.status_code == 401
    with auth_database.session_factory() as db:
        session = db.scalar(select(AuthSession))
        assert session is not None and session.revoked_at is not None


def test_logout_does_not_revoke_another_devices_session(
    auth_client: TestClient,
    second_auth_client: TestClient,
    registered_owner: SessionSummary,
) -> None:
    assert (
        second_auth_client.post(
            "/api/auth/login", json={"email": "alex@example.com", "password": "Correct horse 123!"}
        ).status_code
        == 200
    )
    assert auth_client.post("/api/auth/logout").status_code == 204
    assert auth_client.get("/api/auth/me").status_code == 401
    assert second_auth_client.get("/api/auth/me").status_code == 200


def test_database_expiry_is_enforced_even_with_an_unexpired_jwt(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    auth_database: Database,
) -> None:
    with auth_database.session_factory() as db:
        session = db.scalar(select(AuthSession))
        assert session is not None
        session.expires_at = unix_time() - 1
        db.commit()
    assert auth_client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    "claim,value",
    [
        ("exp", 1),
        ("aud", "public-assistant"),
        ("iss", "another-issuer"),
        ("token_type", "assistant"),
    ],
)
def test_invalid_signed_claims_are_rejected(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    auth_settings: Settings,
    claim: str,
    value: str | int,
) -> None:
    token = auth_client.cookies.get(SESSION_COOKIE_NAME)
    assert token is not None
    claims = decode_session_token(token, auth_settings.auth_secret_key).model_dump(mode="json")
    claims[claim] = value
    invalid = jwt.encode(
        claims, auth_settings.auth_secret_key.get_secret_value(), algorithm="HS256"
    )
    response = auth_client.get(
        "/api/auth/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}={invalid}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize("algorithm", ["HS256", "none"])
def test_invalid_or_missing_signature_cannot_authenticate(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    auth_settings: Settings,
    algorithm: str,
) -> None:
    original = auth_client.cookies.get(SESSION_COOKIE_NAME)
    assert original is not None
    claims = decode_session_token(original, auth_settings.auth_secret_key).model_dump(mode="json")
    key = "different-test-signing-key-at-least-32-bytes" if algorithm == "HS256" else None
    invalid = jwt.encode(claims, key, algorithm=algorithm)
    response = auth_client.get(
        "/api/auth/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}={invalid}"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize("origin", ["https://untrusted.example", "null", ""])
def test_account_mutations_require_an_explicit_allowed_origin(
    auth_client: TestClient,
    registration_payload: dict[str, str],
    auth_database: Database,
    origin: str,
) -> None:
    response = auth_client.post(
        "/api/auth/register", json=registration_payload, headers={"Origin": origin}
    )
    assert response.status_code == 403
    with auth_database.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Organization)) == 0


def test_cross_origin_logout_cannot_revoke_the_session(
    auth_client: TestClient,
    registered_owner: SessionSummary,
) -> None:
    assert (
        auth_client.post(
            "/api/auth/logout", headers={"Origin": "https://untrusted.example"}
        ).status_code
        == 403
    )
    assert auth_client.get("/api/auth/me").status_code == 200


def test_registration_rolls_back_all_records_on_session_insert_failure(
    auth_client: TestClient,
    auth_database: Database,
    registration_payload: dict[str, str],
) -> None:
    def fail_session_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO auth_sessions"):
            raise IntegrityError("injected session insert failure", {}, Exception("test failure"))

    event.listen(auth_database.engine, "before_cursor_execute", fail_session_insert)
    try:
        response = auth_client.post("/api/auth/register", json=registration_payload)
    finally:
        event.remove(auth_database.engine, "before_cursor_execute", fail_session_insert)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_unavailable"
    assert SESSION_COOKIE_NAME not in auth_client.cookies
    with auth_database.session_factory() as db:
        for model in (Organization, User, Assistant, AuthSession):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def test_corrupt_password_storage_is_not_reported_as_bad_credentials(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    auth_database: Database,
) -> None:
    with auth_database.session_factory() as db:
        user = db.get(User, registered_owner.user.id)
        assert user is not None
        user.password_hash = "corrupt"
        db.commit()
    response = auth_client.post(
        "/api/auth/login", json={"email": "alex@example.com", "password": "Correct horse 123!"}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_unavailable"


def test_accounts_and_sessions_survive_application_restart(
    auth_settings: Settings,
    registration_payload: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.auth.security.PASSWORD_ROUNDS", 4)
    settings = auth_settings.model_copy(update={"auth_secret_key": SecretStr("")})
    with TestClient(create_app(settings), headers={"Origin": "http://127.0.0.1:5173"}) as first:
        response = first.post("/api/auth/register", json=registration_payload)
        assert response.status_code == 201
        user_id = response.json()["user"]["id"]
        token = first.cookies.get(SESSION_COOKIE_NAME)
    first_key = load_signing_key(settings)
    with TestClient(create_app(settings)) as restarted:
        response = restarted.get(
            "/api/auth/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"}
        )
        assert response.status_code == 200
        assert response.json()["user"]["id"] == user_id
    assert load_signing_key(settings) == first_key


def test_secure_cookie_configuration(
    auth_settings: Settings,
    registration_payload: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.auth.security.PASSWORD_ROUNDS", 4)
    settings = auth_settings.model_copy(update={"auth_cookie_secure": True})
    with TestClient(
        create_app(settings),
        base_url="https://testserver",
        headers={"Origin": "http://127.0.0.1:5173"},
    ) as client:
        response = client.post("/api/auth/register", json=registration_payload)
        assert response.status_code == 201
        assert "Secure" in response.headers["set-cookie"]
        assert client.get("/api/auth/me").status_code == 200


def test_invalid_signing_key_file_is_not_silently_replaced(auth_settings: Settings) -> None:
    settings = auth_settings.model_copy(update={"auth_secret_key": SecretStr("")})
    settings.auth_secret_file.write_text("invalid", encoding="utf-8")
    with pytest.raises(RuntimeError, match="signing key is invalid"):
        load_signing_key(settings)
    assert settings.auth_secret_file.read_text(encoding="utf-8") == "invalid"


@pytest.mark.parametrize("key", ["weak", " " * 32])
def test_weak_explicit_signing_keys_are_rejected(key: str) -> None:
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(_env_file=None, auth_secret_key=SecretStr(key))


def test_wildcard_auth_origins_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, auth_allowed_origins=["*"])
