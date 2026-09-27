from uuid import uuid4

import jwt
import pytest
from app.auth.schemas import SessionSummary
from app.auth.security import decode_session_token
from app.config import SESSION_COOKIE_NAME, Settings
from app.db import Database
from app.models import Assistant
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture
def second_owner(second_auth_client: TestClient) -> SessionSummary:
    response = second_auth_client.post(
        "/api/auth/register",
        json={
            "organization_name": "Acme Test",
            "full_name": "Sam Owner",
            "email": "sam@example.com",
            "password": "Another correct pass 123!",
        },
    )
    assert response.status_code == 201, response.text
    return SessionSummary.model_validate(response.json())


def test_unauthenticated_requests_cannot_access_account_data(auth_client: TestClient) -> None:
    for path in ("/api/auth/me", f"/api/organizations/{uuid4()}"):
        response = auth_client.get(path)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"


def test_each_account_can_only_read_its_own_organization(
    auth_client: TestClient,
    second_auth_client: TestClient,
    registered_owner: SessionSummary,
    second_owner: SessionSummary,
) -> None:
    own = auth_client.get(f"/api/organizations/{registered_owner.organization.id}")
    other_own = second_auth_client.get(f"/api/organizations/{second_owner.organization.id}")
    assert own.status_code == other_own.status_code == 200
    assert own.json()["name"] == "Northbridge Test"
    assert other_own.json()["name"] == "Acme Test"
    foreign = auth_client.get(f"/api/organizations/{second_owner.organization.id}")
    reverse = second_auth_client.get(f"/api/organizations/{registered_owner.organization.id}")
    unknown = auth_client.get(f"/api/organizations/{uuid4()}")
    assert foreign.status_code == reverse.status_code == unknown.status_code == 404
    assert foreign.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert "Acme Test" not in foreign.text


def test_query_parameters_cannot_select_another_tenant(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    second_owner: SessionSummary,
) -> None:
    response = auth_client.get("/api/auth/me", params={"org_id": second_owner.organization.id})
    assert response.status_code == 200
    assert response.json()["organization"]["id"] == registered_owner.organization.id


@pytest.mark.parametrize("transport", ["cookie", "bearer", "query"])
def test_assistant_token_cannot_authenticate_admin_requests(
    second_auth_client: TestClient,
    auth_database: Database,
    registered_owner: SessionSummary,
    transport: str,
) -> None:
    with auth_database.session_factory() as db:
        token = db.scalar(
            select(Assistant.token).where(Assistant.org_id == registered_owner.organization.id)
        )
    assert token is not None
    if transport == "cookie":
        response = second_auth_client.get(
            "/api/auth/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}={token}"}
        )
    elif transport == "bearer":
        response = second_auth_client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
    else:
        response = second_auth_client.get("/api/auth/me", params={"token": token})
    assert response.status_code == 401


def test_signed_org_claim_must_match_session_ownership(
    auth_client: TestClient,
    registered_owner: SessionSummary,
    second_owner: SessionSummary,
    auth_settings: Settings,
) -> None:
    original = auth_client.cookies.get(SESSION_COOKIE_NAME)
    assert original is not None
    claims = decode_session_token(original, auth_settings.auth_secret_key).model_dump(mode="json")
    claims["org_id"] = second_owner.organization.id
    forged = jwt.encode(claims, auth_settings.auth_secret_key.get_secret_value(), algorithm="HS256")
    response = auth_client.get(
        "/api/auth/me", headers={"Cookie": f"{SESSION_COOKIE_NAME}={forged}"}
    )
    assert response.status_code == 401


def test_registration_cannot_reuse_an_existing_tenant_id(
    second_auth_client: TestClient,
    registered_owner: SessionSummary,
) -> None:
    response = second_auth_client.post(
        "/api/auth/register",
        json={
            "organization_name": "Impostor",
            "full_name": "Another Person",
            "email": "impostor@example.com",
            "password": "An entirely different pass 123!",
            "org_id": registered_owner.organization.id,
        },
    )
    assert response.status_code == 400
