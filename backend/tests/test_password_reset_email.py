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
    payload = {"token":token, "new_password":"new-private-password-456"}
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
    assert client.post("/api/v1/auth/password-reset/confirm", json={"token":token,"new_password":"new-private-password-456"}).status_code == 400
    assert client.post("/api/v1/auth/login", json={"identifier":email,"password":"old-private-password-123"}).status_code == 200
