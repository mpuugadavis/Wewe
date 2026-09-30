"""Focused regression tests for case-insensitive email uniqueness (Phase 1B)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User
from app.security import hash_password


def test_db_level_case_insensitive_email_duplicate_rejected(database: Session) -> None:
    """Same email with different capitalization is rejected at the database level."""
    user1 = User(
        name="Davis First",
        email="Davis@example.com",
        phone="+256700111221",
        password_hash=hash_password("strong-campus-password-42"),
        role="CUSTOMER",
        status="ACTIVE",
    )
    database.add(user1)
    database.flush()

    user2 = User(
        name="Davis Second",
        email="davis@example.com",
        phone="+256700111222",
        password_hash=hash_password("strong-campus-password-42"),
        role="CUSTOMER",
        status="ACTIVE",
    )
    database.add(user2)
    with pytest.raises(IntegrityError):
        database.flush()
    database.rollback()


def test_db_level_distinct_emails_accepted(database: Session) -> None:
    """Distinct email addresses are accepted without conflict."""
    user1 = User(
        name="User A",
        email="alice@example.com",
        phone="+256700111223",
        password_hash=hash_password("strong-campus-password-42"),
        role="CUSTOMER",
        status="ACTIVE",
    )
    user2 = User(
        name="User B",
        email="bob@example.com",
        phone="+256700111224",
        password_hash=hash_password("strong-campus-password-42"),
        role="CUSTOMER",
        status="ACTIVE",
    )
    database.add_all([user1, user2])
    database.flush()

    retrieved_a = database.scalar(select(User).where(User.email == "alice@example.com"))
    retrieved_b = database.scalar(select(User).where(User.email == "bob@example.com"))
    assert retrieved_a is not None
    assert retrieved_b is not None


def test_db_level_null_emails_allowed_for_multiple_users(database: Session) -> None:
    """Users with NULL email (e.g. phone-only users) do not collide on the unique index."""
    user1 = User(
        name="Phone Only 1",
        email=None,
        phone="+256700111225",
        password_hash=hash_password("strong-campus-password-42"),
        role="CUSTOMER",
        status="ACTIVE",
    )
    user2 = User(
        name="Phone Only 2",
        email=None,
        phone="+256700111226",
        password_hash=hash_password("strong-campus-password-42"),
        role="CUSTOMER",
        status="ACTIVE",
    )
    database.add_all([user1, user2])
    database.flush()

    assert user1.id is not None
    assert user2.id is not None


def test_api_registration_rejects_case_insensitive_duplicate(client: TestClient) -> None:
    """API registration rejects email differing only in capitalization (HTTP 409)."""
    resp1 = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Davis One",
            "email": "Davis@example.com",
            "phone": "+256700111231",
            "password": "strong-campus-password-42",
            "role": "CUSTOMER",
        },
    )
    assert resp1.status_code == 201

    # Attempt registration with all-lowercase version of the same email
    resp2 = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Davis Two",
            "email": "davis@example.com",
            "phone": "+256700111232",
            "password": "strong-campus-password-42",
            "role": "CUSTOMER",
        },
    )
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "account_exists"

    # Attempt registration with ALL-UPPERCASE version of the same email
    resp3 = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Davis Three",
            "email": "DAVIS@EXAMPLE.COM",
            "phone": "+256700111233",
            "password": "strong-campus-password-42",
            "role": "CUSTOMER",
        },
    )
    assert resp3.status_code == 409
    assert resp3.json()["error"]["code"] == "account_exists"


def test_existing_accounts_and_authentication_lookup(client: TestClient, database: Session) -> None:
    """Existing accounts continue to work, and authentication lookup works regardless of input casing."""
    # Seed an account with mixed-case email directly into the DB to simulate existing legacy rows
    user = User(
        name="Legacy Mixed Case",
        email="LegacyUser@Domain.Com",
        phone="+256700111241",
        password_hash=hash_password("strong-campus-password-42"),
        role="CUSTOMER",
        status="ACTIVE",
    )
    database.add(user)
    database.commit()

    # Login using exact case
    login_exact = client.post(
        "/api/v1/auth/login",
        json={"identifier": "LegacyUser@Domain.Com", "password": "strong-campus-password-42"},
    )
    assert login_exact.status_code == 200
    assert "access_token" in login_exact.json()

    # Login using all lowercase
    login_lower = client.post(
        "/api/v1/auth/login",
        json={"identifier": "legacyuser@domain.com", "password": "strong-campus-password-42"},
    )
    assert login_lower.status_code == 200

    # Login using all uppercase
    login_upper = client.post(
        "/api/v1/auth/login",
        json={"identifier": "LEGACYUSER@DOMAIN.COM", "password": "strong-campus-password-42"},
    )
    assert login_upper.status_code == 200

    # Password reset lookup works regardless of input casing
    reset_resp = client.post(
        "/api/v1/auth/password-reset/request",
        json={"identifier": "LEGACYUSER@DOMAIN.COM"},
    )
    assert reset_resp.status_code == 202
    assert "development_token" in reset_resp.json()
