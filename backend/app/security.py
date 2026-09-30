import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from pwdlib import PasswordHash

from app.config import get_settings

_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


def new_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user_id: UUID, token_version: int, session_id: UUID) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "sid": str(session_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "iss": "wewe-api",
        "aud": "wewe-client",
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm="HS256")


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(
        token,
        settings.secret_key.get_secret_value(),
        algorithms=["HS256"],
        issuer="wewe-api",
        audience="wewe-client",
        options={"require": ["sub", "ver", "sid", "exp", "iat"]},
    )
