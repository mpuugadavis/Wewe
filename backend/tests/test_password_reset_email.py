import re
from datetime import timedelta
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from app.models import User, NotificationOutbox, PasswordResetToken, utcnow
from app.routers import auth


@pytest.mark.parametrize("role", ["CUSTOMER", "ADMIN"])
def test_brevo_reset_is_private_one_time_and_invalidates_sessions(client, database, monkeypatch, role):
    email = "recover@example.test"
    original = "old-private-password-123"
    assert client.post("/api/v1/auth/register", json={"name":"Account owner", "email":email, "password":original}).status_code == 201
    user = database.scalar(select(User).where(User.email == email))
    user.role = role
    database.commit()
    old_tokens = client.post("/api/v1/auth/login", json={"identifier":email,"password":original}).json()
    settings = auth.get_settings().model_copy(update={"app_env":"staging", "email_transport":"BREVO_API", "brevo_api_key":SecretStr("test-api-key"), "smtp_host":None})
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    known = client.post("/api/v1/auth/password-reset/request", json={"identifier":email})
    unknown = client.post("/api/v1/auth/password-reset/request", json={"identifier":"unknown@example.test"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert "development_token" not in known.json()
    jobs = database.scalars(select(NotificationOutbox).where(NotificationOutbox.event_type == "PASSWORD_RESET")).all()
    assert len(jobs) == 1 and jobs[0].channel == "EMAIL"
    assert jobs[0].payload["to"] == email
    token = re.search(r"\n\n(\S+)\n\n", jobs[0].payload["body"]).group(1)
    assert len(token) == 6 and token.isdigit()
    payload = {"identifier":email,"token":token, "new_password":"new-private-password-456"}
    assert client.post("/api/v1/auth/password-reset/confirm", json=payload).status_code == 204
    assert client.post("/api/v1/auth/password-reset/confirm", json=payload).status_code == 400
    assert client.post("/api/v1/auth/login", json={"identifier":email,"password":original}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"identifier":email,"password":payload["new_password"]}).status_code == 200
    assert client.get("/api/v1/auth/me", headers={"Authorization":"Bearer " + old_tokens["access_token"]}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token":old_tokens["refresh_token"]}).status_code == 401


def test_expired_reset_token_cannot_change_password(client, database):
    email = "expired@example.test"
    client.post("/api/v1/auth/register", json={"name":"Account owner", "email":email, "password":"old-private-password-123"})
    response = client.post("/api/v1/auth/password-reset/request", json={"identifier":email})
    token = response.json()["development_token"]
    record = database.scalar(select(PasswordResetToken))
    record.expires_at = utcnow() - timedelta(seconds=1)
    database.commit()
    assert client.post("/api/v1/auth/password-reset/confirm", json={"identifier":email,"token":token,"new_password":"new-private-password-456"}).status_code == 400
    assert client.post("/api/v1/auth/login", json={"identifier":email,"password":"old-private-password-123"}).status_code == 200


def test_new_six_digit_code_replaces_old_and_is_account_bound(client, database, monkeypatch):
    for email in ("first@example.test", "other@example.test"):
        client.post("/api/v1/auth/register", json={"name":"Owner", "email":email, "password":"old-private-password-123"})
    sequence = iter([7,8])
    monkeypatch.setattr(auth.secrets, "randbelow", lambda maximum: next(sequence))
    first = client.post("/api/v1/auth/password-reset/request", json={"identifier":"first@example.test"}).json()["development_token"]
    latest = client.post("/api/v1/auth/password-reset/request", json={"identifier":"first@example.test"}).json()["development_token"]
    assert first == "000007" and latest == "000008"
    payload = {"identifier":"other@example.test", "token":latest, "new_password":"new-private-password-456"}
    assert client.post("/api/v1/auth/password-reset/confirm", json=payload).status_code == 400
    payload.update(identifier="first@example.test", token=first)
    assert client.post("/api/v1/auth/password-reset/confirm", json=payload).status_code == 400
    payload["token"] = latest
    assert client.post("/api/v1/auth/password-reset/confirm", json=payload).status_code == 204


def test_five_wrong_attempts_lock_code_even_from_another_ip(client, database):
    from fastapi import HTTPException
    from starlette.requests import Request
    from app.schemas import ResetConfirmIn
    client.post("/api/v1/auth/register", json={"name":"Owner", "email":"locked@example.test", "password":"old-private-password-123"})
    code = client.post("/api/v1/auth/password-reset/request", json={"identifier":"locked@example.test"}).json()["development_token"]
    wrong = "000000" if code != "000000" else "111111"
    for attempt in range(5):
        assert client.post("/api/v1/auth/password-reset/confirm", json={"identifier":"locked@example.test", "token":wrong,"new_password":"new-private-password-456"}).status_code == 400
    token = database.scalar(select(PasswordResetToken))
    assert token.failed_attempts == 5 and token.consumed_at is not None
    request = Request({"type":"http", "method":"POST", "path":"/", "headers":[], "client":("192.0.2.2",1)})
    with pytest.raises(HTTPException) as error:
        auth.confirm_password_reset.__wrapped__(request, ResetConfirmIn(identifier="locked@example.test",token=code,new_password="new-private-password-456"), db=database)
    assert error.value.status_code == 400


def test_account_request_limit_survives_ip_changes(client, database):
    from app.security import hash_token
    from uuid import uuid4
    client.post("/api/v1/auth/register", json={"name":"Owner", "email":"limited@example.test", "password":"old-private-password-123"})
    user = database.scalar(select(User))
    for count in range(4):
        database.add(PasswordResetToken(user_id=user.id,token_hash=hash_token(str(uuid4())),expires_at=utcnow()+timedelta(minutes=30)))
    database.commit()
    response = client.post("/api/v1/auth/password-reset/request", json={"identifier":"limited@example.test"})
    assert response.status_code == 202 and "development_token" not in response.json()
    assert len(database.scalars(select(PasswordResetToken)).all()) == 4
