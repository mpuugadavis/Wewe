import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import engine
from app.limiter import limiter
from app.routers import accounts, admin, auth, catalog, commerce, locations, operations, payments
from app.services.payment_sandbox import configure_simulated_providers

settings = get_settings()
if settings.payment_mode == "SIMULATED":
    configure_simulated_providers()
logging.basicConfig(level=logging.INFO if settings.app_env != "production" else logging.WARNING)
logger = logging.getLogger("wewe.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    yield


app = FastAPI(
    title="WEWE API",
    summary="Marketplace, ordering and campus delivery APIs",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/openapi.json" if settings.app_env != "production" else None,
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url=None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Webhook-Signature", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
    if settings.app_env == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def error_response(status_code: int, code: str, message: str, request_id: str | None = None, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}, "request_id": request_id},
        headers=headers,
    )


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code", "request_failed"))
        message = str(detail.get("message", "The request could not be completed."))
    else:
        code = "request_failed"
        message = str(detail)
    return error_response(exc.status_code, code, message, getattr(request.state, "request_id", None), exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, _exc: RequestValidationError):
    return error_response(422, "validation_error", "One or more request fields are invalid.", getattr(request.state, "request_id", None))


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, _exc: IntegrityError):
    return error_response(409, "data_conflict", "The requested change conflicts with existing data.", getattr(request.state, "request_id", None))


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.error("Unhandled API exception request_id=%s type=%s", request_id, type(exc).__name__)
    return error_response(500, "internal_error", "An unexpected error occurred.", request_id)


@app.get("/health/live", tags=["health"])
def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready"}


for api_router in (auth.router, accounts.router, catalog.router, locations.router, commerce.router, operations.router, payments.router, admin.router):
    app.include_router(api_router, prefix=settings.api_prefix)
