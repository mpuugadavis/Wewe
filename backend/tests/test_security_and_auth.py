from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.schemas import RegisterIn
from app.security import hash_password, verify_password


def test_password_hash_is_not_plaintext() -> None:
    password = "correct-horse-campus-42"
    stored = hash_password(password)
    assert stored != password
    assert verify_password(password, stored)
    assert not verify_password("wrong-password", stored)


def test_public_registration_cannot_create_admin() -> None:
    with pytest.raises(ValidationError):
        RegisterIn(name="Untrusted", email="user@example.test", password="long-enough-password", role="ADMIN")


def test_registration_rejects_invalid_email_format(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Invalid Email",
            "email": "not-an-email",
            "phone": "+256700000051",
            "password": "strong-campus-password-42",
            "role": "CUSTOMER",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_verification_requests_are_rate_limited(client: TestClient) -> None:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Verification Test",
            "email": "verification@example.test",
            "password": "strong-campus-password-42",
            "role": "CUSTOMER",
        },
    )
    assert registered.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={
            "identifier": "verification@example.test",
            "password": "strong-campus-password-42",
        },
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    responses = [
        client.post(
            "/api/v1/auth/verification/request",
            json={"purpose": "EMAIL"},
            headers=headers,
        )
        for _ in range(5)
    ]

    assert [response.status_code for response in responses] == [202, 202, 202, 202, 429]


def test_registration_login_and_customer_role_guard(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Amina N.", "email": "amina@example.test", "phone": "+256700111222", "password": "strong-campus-password-42", "role": "CUSTOMER"},
    )
    assert response.status_code == 201
    user = response.json()
    assert user["role"] == "CUSTOMER"
    assert "password_hash" not in user

    login = client.post("/api/v1/auth/login", json={"identifier": "AMINA@example.test", "password": "strong-campus-password-42"})
    assert login.status_code == 200
    access_token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert client.get("/api/v1/retailers/me/products", headers=headers).status_code == 403
    assert client.get("/api/v1/cart").status_code == 401


def test_refresh_rotation_reuse_revokes_token_family(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"name": "Amina N.", "email": "refresh@example.test", "password": "strong-campus-password-42", "role": "CUSTOMER"},
    )
    login = client.post("/api/v1/auth/login", json={"identifier": "refresh@example.test", "password": "strong-campus-password-42"})
    first_refresh = login.json()["refresh_token"]
    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert rotated.status_code == 200
    second = rotated.json()
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert replay.status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {second['access_token']}"}).status_code == 401


def test_password_reset_invalidates_existing_access(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"name": "Amina N.", "email": "reset@example.test", "password": "strong-campus-password-42", "role": "CUSTOMER"},
    )
    login = client.post("/api/v1/auth/login", json={"identifier": "reset@example.test", "password": "strong-campus-password-42"})
    access = login.json()["access_token"]
    reset = client.post("/api/v1/auth/password-reset/request", json={"identifier": "reset@example.test"})
    token = reset.json()["development_token"]
    changed = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"identifier": "reset@example.test", "token": token, "new_password": "new-strong-campus-password-43"},
    )
    assert changed.status_code == 204
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"identifier": "reset@example.test", "password": "new-strong-campus-password-43"}).status_code == 200
