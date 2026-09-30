from dataclasses import dataclass
from typing import Callable
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import RefreshTokenFamily, User
from app.security import decode_access_token

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user: User
    session_id: UUID


def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Principal:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "authentication_required", "message": "Valid authentication is required."},
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        claims = decode_access_token(credentials.credentials)
        user_id = UUID(claims["sub"])
        session_id = UUID(claims["sid"])
        token_version = int(claims["ver"])
    except (jwt.InvalidTokenError, ValueError, KeyError, TypeError):
        raise unauthorized from None
    user = db.get(User, user_id)
    family = db.get(RefreshTokenFamily, session_id)
    if (
        user is None
        or family is None
        or family.user_id != user.id
        or family.revoked_at is not None
        or user.status != "ACTIVE"
        or family.token_version != token_version
        or user.token_version != token_version
    ):
        raise unauthorized
    return Principal(user=user, session_id=session_id)


def require_roles(*roles: str) -> Callable:
    allowed = frozenset(roles)

    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "forbidden", "message": "This role cannot perform that operation."},
            )
        return principal

    return dependency
