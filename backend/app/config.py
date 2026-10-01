from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./wewe.db"
    secret_key: SecretStr
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    password_reset_minutes: int = 30
    cors_origins: str = "http://localhost:5500,http://127.0.0.1:5500"
    payment_callback_url: str = "http://localhost:8000/api/v1/payments/webhooks"
    payment_webhook_secret: SecretStr | None = None
    payment_mode: Literal["DISABLED", "SIMULATED", "EXTERNAL"] = "DISABLED"
    rate_limit_storage_uri: str = "memory://"
    email_from: str = "no-reply@example.invalid"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    sms_provider: str | None = None
    sms_api_url: str | None = None
    sms_api_key: SecretStr | None = None
    mtn_momo_api_key: SecretStr | None = None
    mtn_momo_api_secret: SecretStr | None = None
    airtel_money_api_key: SecretStr | None = None
    airtel_money_api_secret: SecretStr | None = None
    #: Road-route distance for delivery pricing (COM-FEE-004). Google Maps is
    #: opt-in because it requires a billed Cloud project/key. OSRM is the
    #: safe local-development default and still uses a real road route.
    routing_provider: Literal["GOOGLE_MAPS", "OSRM"] = "OSRM"
    google_maps_api_key: SecretStr | None = None
    #: Browser-restricted key used only by the Maps JavaScript API in the WEWE frontend.
    google_maps_browser_api_key: str | None = None
    #: Optional override of the routing service base URL (proxy or self-hosted
    #: OSRM instance). When unset the provider's public endpoint is used.
    routing_base_url: str | None = None
    routing_timeout_seconds: float = 5.0
    routing_user_agent: str = "WEWE-campus-delivery/1.0"
    storage_bucket: str | None = None
    storage_endpoint: str | None = None
    storage_access_key: SecretStr | None = None
    storage_secret_key: SecretStr | None = None
    #: Optional exact host allow-list for catalog image URLs. Empty means any HTTPS host.
    media_allowed_hosts: str = ""
    #: Future authenticated upload adapters must enforce this byte limit before storage.
    media_max_upload_bytes: int = 5_242_880

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if len(secret) < 32 or "replace-with" in secret.lower():
            raise ValueError("SECRET_KEY must contain at least 32 characters")
        return value

    @field_validator("access_token_minutes", "refresh_token_days", "password_reset_minutes")
    @classmethod
    def validate_positive_expiry(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("token expiry settings must be positive")
        return value

    @field_validator("routing_timeout_seconds")
    @classmethod
    def validate_positive_routing_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("ROUTING_TIMEOUT_SECONDS must be positive")
        return value

    @field_validator("media_max_upload_bytes")
    @classmethod
    def validate_positive_media_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("MEDIA_MAX_UPLOAD_BYTES must be positive")
        return value

    @field_validator("google_maps_api_key")
    @classmethod
    def require_a_real_google_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and "replace" in value.get_secret_value().lower():
            raise ValueError("GOOGLE_MAPS_API_KEY must be a real key or be left empty")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_production_cors(self) -> "Settings":
        if self.app_env == "production" and "*" in self.cors_origin_list:
            raise ValueError("Wildcard CORS origins are forbidden in production")
        if self.app_env == "production" and not self.smtp_host:
            raise ValueError("SMTP_HOST must be configured in production for account recovery")
        if self.app_env == "production" and not self.database_url.lower().startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("DATABASE_URL must use PostgreSQL in production")
        if self.app_env == "production" and not self.rate_limit_storage_uri.lower().startswith(("redis://", "rediss://")):
            raise ValueError("RATE_LIMIT_STORAGE_URI must use Redis in production")
        if self.app_env == "production" and self.payment_mode == "SIMULATED":
            raise ValueError("PAYMENT_MODE=SIMULATED is forbidden in production")
        if self.app_env == "production" and self.payment_mode == "EXTERNAL" and not self.payment_webhook_secret:
            raise ValueError("PAYMENT_WEBHOOK_SECRET must be configured in production")
        if self.payment_webhook_secret:
            webhook_secret = self.payment_webhook_secret.get_secret_value()
            if len(webhook_secret) < 32 or "replace" in webhook_secret.lower():
                raise ValueError("PAYMENT_WEBHOOK_SECRET must be a unique secret of at least 32 characters")
        if self.app_env == "production" and urlsplit(self.payment_callback_url).scheme != "https":
            raise ValueError("PAYMENT_CALLBACK_URL must use HTTPS in production")
        if self.routing_provider == "GOOGLE_MAPS" and not self.google_maps_api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY is required when ROUTING_PROVIDER is GOOGLE_MAPS")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
