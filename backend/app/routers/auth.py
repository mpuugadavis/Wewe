from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.dependencies import Principal, get_principal
from app.limiter import limiter
from app.models import (
    CustomerProfile,
    DeliveryAgent,
    PasswordResetToken,
    RefreshToken,
    RefreshTokenFamily,
    Retailer,
    User,
    VerificationToken,
    utcnow,
)
from app.schemas import (
    LoginIn,
    RefreshIn,
    RegisterIn,
    ResetConfirmIn,
    ResetRequestIn,
    TokenPair,
    UserOut,
    VerificationConfirmIn,
    VerificationRequestIn,
)
from app.security import create_access_token, hash_password, hash_token, new_opaque_token, verify_password
from app.services.mailer import send_email

router = APIRouter(prefix="/auth", tags=["authentication"])


def issue_token_pair(db: Session, user: User, family_id: UUID | None = None) -> TokenPair:
    settings = get_settings()
    refresh_token = new_opaque_token()
    if family_id is None:
        family = RefreshTokenFamily(user_id=user.id, token_version=user.token_version)
        db.add(family)
        db.flush()
        family_id = family.id
    db.add(
        RefreshToken(
            family_id=family_id,
            token_hash=hash_token(refresh_token),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
        )
    )
    db.flush()
    return TokenPair(
        access_token=create_access_token(user.id, user.token_version, family_id),
        refresh_token=refresh_token,
        expires_in=settings.access_token_minutes * 60,
    )


def _slug(value: str) -> str:
    import re

    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:180] or "retailer"


def _expired(value: datetime) -> bool:
    comparable = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return comparable <= datetime.now(timezone.utc)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, payload: RegisterIn, db: Session = Depends(get_db)) -> User:
    email = str(payload.email).lower() if payload.email else None
    phone = payload.phone
    existing = db.scalar(
        select(User).where(
            or_(func_lower_email(email), User.phone == phone) if email and phone
            else func_lower_email(email) if email
            else User.phone == phone
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail={"code": "account_exists", "message": "An account already uses that contact."})
    user = User(
        name=payload.name.strip(),
        email=email,
        phone=phone,
        password_hash=hash_password(payload.password),
        role=payload.role,
        status="ACTIVE",
    )
    db.add(user)
    try:
        db.flush()
        if payload.role == "CUSTOMER":
            db.add(CustomerProfile(user_id=user.id))
        elif payload.role == "RETAILER":
            assert payload.business_name is not None
            slug = _slug(payload.business_name)
            if db.scalar(select(Retailer.id).where(Retailer.slug == slug)):
                slug = f"{slug}-{str(user.id)[:8]}"
            db.add(
                Retailer(
                    user_id=user.id,
                    business_name=payload.business_name.strip(),
                    slug=slug,
                    phone=phone or "",
                    verification_status="PENDING",
                    status="ACTIVE",
                )
            )
        else:
            assert phone is not None
            db.add(DeliveryAgent(user_id=user.id, phone=phone, transport_mode=payload.transport_mode))
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "account_exists", "message": "An account already uses that contact."}) from None
    return user


def func_lower_email(email: str | None):
    from sqlalchemy import func

    return func.lower(User.email) == email if email else User.email.is_(None)


@router.post("/login", response_model=TokenPair)
@limiter.limit("5/minute")
def login(request: Request, payload: LoginIn, db: Session = Depends(get_db)) -> TokenPair:
    identifier = payload.identifier.strip()
    user = db.scalar(
        select(User).where(
            or_(func_lower_email(identifier.lower()), User.phone == identifier)
        )
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail={"code": "invalid_credentials", "message": "Invalid login details."})
    if user.status != "ACTIVE":
        raise HTTPException(status_code=403, detail={"code": "account_inactive", "message": "This account is not active."})
    tokens = issue_token_pair(db, user)
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenPair)
@limiter.limit("20/minute")
def refresh(request: Request, payload: RefreshIn, db: Session = Depends(get_db)) -> TokenPair:
    token = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(payload.refresh_token)).with_for_update()
    )
    invalid = HTTPException(status_code=401, detail={"code": "invalid_refresh_token", "message": "Refresh token is invalid or expired."})
    if token is None:
        raise invalid
    family = db.get(RefreshTokenFamily, token.family_id)
    user = db.get(User, family.user_id) if family else None
    now = utcnow()
    if token.used_at is not None:
        if family and family.revoked_at is None:
            family.revoked_at = now
            db.commit()
        raise invalid
    if (
        family is None
        or family.revoked_at is not None
        or user is None
        or user.status != "ACTIVE"
        or family.token_version != user.token_version
        or _expired(token.expires_at)
    ):
        raise invalid
    token.used_at = now
    pair = issue_token_pair(db, user, family.id)
    db.commit()
    return pair


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> None:
    family = db.get(RefreshTokenFamily, principal.session_id)
    if family and family.revoked_at is None:
        family.revoked_at = utcnow()
        db.commit()


@router.get("/me", response_model=UserOut)
def me(principal: Principal = Depends(get_principal)) -> User:
    return principal.user


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("4/minute")
def request_password_reset(
    request: Request,
    payload: ResetRequestIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    identifier = payload.identifier.strip()
    user = db.scalar(select(User).where(or_(func_lower_email(identifier.lower()), User.phone == identifier)))
    response = {"message": "If the account exists, password-reset instructions will be sent."}
    if user:
        token_value = new_opaque_token()
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(token_value),
                expires_at=utcnow() + timedelta(minutes=get_settings().password_reset_minutes),
            )
        )
        db.commit()
        if user.email and get_settings().smtp_host:
            background_tasks.add_task(
                send_email,
                user.email,
                "Reset your WEWE password",
                f"Use this one-time token in the WEWE password reset form:\n\n{token_value}\n\nIt expires soon. If you did not request this, ignore this email.",
            )
        elif get_settings().app_env in {"development", "test"}:
            response["development_token"] = token_value
    return response


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
def confirm_password_reset(request: Request, payload: ResetConfirmIn, db: Session = Depends(get_db)) -> None:
    token = db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == hash_token(payload.token))
        .with_for_update()
    )
    if token is None or token.consumed_at is not None or _expired(token.expires_at):
        raise HTTPException(status_code=400, detail={"code": "invalid_reset_token", "message": "Reset token is invalid or expired."})
    user = db.get(User, token.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail={"code": "invalid_reset_token", "message": "Reset token is invalid or expired."})
    token.consumed_at = utcnow()
    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1
    db.commit()


@router.post("/verification/request", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("4/minute")
def request_verification(
    payload: VerificationRequestIn,
    request: Request,
    background_tasks: BackgroundTasks,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    user = principal.user
    contact = user.email if payload.purpose == "EMAIL" else user.phone
    if not contact:
        raise HTTPException(status_code=400, detail={"code": "contact_missing", "message": "Add this contact method before verifying it."})
    settings = get_settings()
    can_send_email = payload.purpose == "EMAIL" and bool(settings.smtp_host)
    development_delivery = settings.app_env in {"development", "test"}
    if not can_send_email and not development_delivery:
        raise HTTPException(status_code=503, detail={"code": "verification_delivery_unavailable", "message": "No delivery adapter is configured for this contact method."})
    token_value = new_opaque_token()
    db.add(
        VerificationToken(
            user_id=user.id,
            contact=contact,
            purpose=payload.purpose,
            token_hash=hash_token(token_value),
            expires_at=utcnow() + timedelta(minutes=20),
        )
    )
    db.commit()
    response = {"message": "Verification instructions have been queued."}
    if can_send_email:
        background_tasks.add_task(send_email, contact, "Verify your WEWE account", f"Your one-time verification token is:\n\n{token_value}")
    elif development_delivery:
        response["development_token"] = token_value
    return response


@router.post("/verification/confirm", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
def confirm_verification(request: Request, 
    payload: VerificationConfirmIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> None:
    token = db.scalar(
        select(VerificationToken)
        .where(VerificationToken.token_hash == hash_token(payload.token), VerificationToken.user_id == principal.user.id)
        .with_for_update()
    )
    if token is None or token.consumed_at is not None or _expired(token.expires_at):
        raise HTTPException(status_code=400, detail={"code": "invalid_verification_token", "message": "Verification token is invalid or expired."})
    token.consumed_at = utcnow()
    if token.purpose == "EMAIL":
        principal.user.email_verified_at = utcnow()
    else:
        principal.user.phone_verified_at = utcnow()
    db.commit()
