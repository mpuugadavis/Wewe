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
    trusted_hosts: str = "localhost,127.0.0.1,testserver"
    max_request_body_bytes: int = 2_000_000
    payment_callback_url: str = "http://localhost:8000/api/v1/payments/webhooks"
    payment_webhook_secret: SecretStr | None = None
    payment_mode: Literal["DISABLED", "SIMULATED", "EXTERNAL"] = "DISABLED"
    payment_provider: Literal["PAWAPAY", "FLUTTERWAVE"] = "PAWAPAY"
    pawapay_api_token: SecretStr | None = None
    pawapay_api_base_url: str = "https://api.sandbox.pawapay.io"
    pawapay_environment: Literal["SANDBOX", "LIVE"] = "SANDBOX"
    pawapay_checkout_callback_url: str = "http://localhost:8000/api/v1/payments/pawapay/checkout-callback"
    pawapay_deposit_callback_url: str = "http://localhost:8000/api/v1/payments/pawapay/deposit-callback"
    pawapay_payout_callback_url: str = "http://localhost:8000/api/v1/payments/pawapay/payout-callback"
    pawapay_refund_callback_url: str = "http://localhost:8000/api/v1/payments/pawapay/refund-callback"
    flutterwave_client_id: str | None = None
    flutterwave_client_secret: SecretStr | None = None
    flutterwave_webhook_secret_hash: SecretStr | None = None
    flutterwave_redirect_url: str | None = None
    flutterwave_api_base_url: str = "https://developersandbox-api.flutterwave.com"
    flutterwave_environment: Literal["SANDBOX", "LIVE"] = "SANDBOX"
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
    #: Road-route distance for delivery pricing (COM-FEE-004).
    #: OpenRouteService is the default hosted routing provider. Google Maps and
    #: OSRM remain available as explicit alternatives.
    routing_provider: Literal["OPENROUTESERVICE", "GOOGLE_MAPS", "OSRM"] = "OPENROUTESERVICE"
    openrouteservice_api_key: SecretStr | None = None
    google_maps_api_key: SecretStr | None = None
    #: Browser-restricted key used only by the Maps JavaScript API in the WEWE frontend.
    google_maps_browser_api_key: str | None = None
    #: Optional provider base URL override. For OpenRouteService this should
    #: normally be left empty so the current HeiGIT endpoint is used.
    routing_base_url: str | None = None
    routing_timeout_seconds: float = 12.0
    routing_user_agent: str = "WEWE-campus-delivery/1.0"
    storage_provider: Literal["DISABLED", "S3"] = "DISABLED"
    storage_bucket: str | None = None
    storage_endpoint: str | None = None
    storage_public_base_url: str | None = None
    storage_access_key: SecretStr | None = None
    storage_secret_key: SecretStr | None = None
    #: Optional exact host allow-list for catalog image URLs. Empty means any HTTPS host.
    media_allowed_hosts: str = ""
    #: Future authenticated upload adapters must enforce this byte limit before storage.
    media_max_upload_bytes: int = 5_242_880
    #: Short-lived object-storage read URLs used by the signed-media delivery adapter.
    media_signed_url_ttl_seconds: int = 300
    #: Minimum age before an unreferenced object can be collected.
    media_cleanup_grace_seconds: int = 86_400
    #: Cleanup worker polls at this interval. Destructive cleanup remains opt-in.
    media_cleanup_poll_seconds: float = 300.0
    #: Keep cleanup non-destructive until explicitly enabled in the deployment.
    media_cleanup_dry_run: bool = True
    media_cleanup_prefix: str = "products/"
    worker_health_stale_after_seconds: int = 900
    backup_max_age_seconds: int = 86_400
    notification_worker_batch_size: int = 50
    notification_worker_poll_seconds: float = 2.0
    notification_worker_stale_after_seconds: int = 300
    notification_worker_max_attempts: int = 8

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

    @field_validator("media_cleanup_grace_seconds")
    @classmethod
    def validate_media_cleanup_grace(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("MEDIA_CLEANUP_GRACE_SECONDS must be positive")
        return value

    @field_validator("media_signed_url_ttl_seconds")
    @classmethod
    def validate_media_signed_url_ttl(cls, value: int) -> int:
        if value <= 0 or value > 3600:
            raise ValueError("MEDIA_SIGNED_URL_TTL_SECONDS must be between 1 and 3600")
        return value

    @field_validator("media_cleanup_poll_seconds")
    @classmethod
    def validate_media_cleanup_poll_seconds(cls, value: float) -> float:
        if value <= 0 or value > 86_400:
            raise ValueError("MEDIA_CLEANUP_POLL_SECONDS must be between 0 and 86400")
        return value

    @field_validator("worker_health_stale_after_seconds", "backup_max_age_seconds")
    @classmethod
    def validate_operational_age_settings(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("operational age settings must be positive")
        return value

    @field_validator("notification_worker_batch_size")
    @classmethod
    def validate_notification_batch_size(cls, value: int) -> int:
        if value <= 0 or value > 500:
            raise ValueError("NOTIFICATION_WORKER_BATCH_SIZE must be between 1 and 500")
        return value

    @field_validator("notification_worker_poll_seconds")
    @classmethod
    def validate_notification_poll_seconds(cls, value: float) -> float:
        if value <= 0 or value > 60:
            raise ValueError("NOTIFICATION_WORKER_POLL_SECONDS must be between 0 and 60")
        return value

    @field_validator("notification_worker_stale_after_seconds", "notification_worker_max_attempts")
    @classmethod
    def validate_notification_worker_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("notification worker settings must be positive")
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
    def trusted_host_list(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]

    @field_validator("max_request_body_bytes")
    @classmethod
    def validate_request_body_limit(cls, value: int) -> int:
        if value <= 0 or value > 50_000_000:
            raise ValueError("MAX_REQUEST_BODY_BYTES must be between 1 and 50000000")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_production_cors(self) -> "Settings":
        if self.app_env == "production" and "*" in self.cors_origin_list:
            raise ValueError("Wildcard CORS origins are forbidden in production")
        if self.app_env == "production" and not self.trusted_host_list:
            raise ValueError("TRUSTED_HOSTS must contain at least one host in production")
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
        if self.payment_mode == "EXTERNAL" and (
            not self.flutterwave_client_id
            or not self.flutterwave_client_secret
            or not self.flutterwave_redirect_url
        ):
            raise ValueError(
                "FLUTTERWAVE_CLIENT_ID, FLUTTERWAVE_CLIENT_SECRET and "
                "FLUTTERWAVE_REDIRECT_URL are required when PAYMENT_MODE=EXTERNAL"
            )
        if self.flutterwave_client_id and "replace" in self.flutterwave_client_id.lower():
            raise ValueError("FLUTTERWAVE_CLIENT_ID must be a real client ID or be left empty")
        if self.flutterwave_client_secret:
            flutterwave_client_secret = self.flutterwave_client_secret.get_secret_value()
            if "replace" in flutterwave_client_secret.lower() or len(flutterwave_client_secret) < 16:
                raise ValueError("FLUTTERWAVE_CLIENT_SECRET must be a real client secret or be left empty")
        if self.app_env == "production" and self.payment_mode == "EXTERNAL" and self.payment_provider == "FLUTTERWAVE" and self.flutterwave_environment == "SANDBOX":
            raise ValueError("Flutterwave sandbox payments are forbidden in production")
        if self.app_env == "production" and self.payment_mode == "EXTERNAL" and self.payment_provider == "FLUTTERWAVE" and self.flutterwave_redirect_url:
            if urlsplit(self.flutterwave_redirect_url).scheme != "https":
                raise ValueError("FLUTTERWAVE_REDIRECT_URL must use HTTPS in production")
        if self.flutterwave_webhook_secret_hash and self.payment_provider == "FLUTTERWAVE":
            webhook_hash = self.flutterwave_webhook_secret_hash.get_secret_value()
            if "replace" in webhook_hash.lower() or len(webhook_hash) < 16:
                raise ValueError("FLUTTERWAVE_WEBHOOK_SECRET_HASH must be a real webhook secret hash or be left empty")
        if self.payment_webhook_secret:
            webhook_secret = self.payment_webhook_secret.get_secret_value()
            if len(webhook_secret) < 32 or "replace" in webhook_secret.lower():
                raise ValueError("PAYMENT_WEBHOOK_SECRET must be a unique secret of at least 32 characters")
        if self.app_env == "production" and self.payment_provider == "PAWAPAY" and urlsplit(self.pawapay_checkout_callback_url).scheme != "https":
            raise ValueError("PAWAPAY_CHECKOUT_CALLBACK_URL must use HTTPS in production")
        if self.app_env == "production" and self.payment_provider == "PAWAPAY" and urlsplit(self.pawapay_deposit_callback_url).scheme != "https":
            raise ValueError("PAWAPAY_DEPOSIT_CALLBACK_URL must use HTTPS in production")
        if self.app_env == "production" and self.payment_provider == "PAWAPAY" and urlsplit(self.pawapay_payout_callback_url).scheme != "https":
            raise ValueError("PAWAPAY_PAYOUT_CALLBACK_URL must use HTTPS in production")
        if self.app_env == "production" and self.payment_provider == "PAWAPAY" and urlsplit(self.pawapay_refund_callback_url).scheme != "https":
            raise ValueError("PAWAPAY_REFUND_CALLBACK_URL must use HTTPS in production")
        if self.app_env == "production" and self.payment_provider == "FLUTTERWAVE" and urlsplit(self.payment_callback_url).scheme != "https":
            raise ValueError("PAYMENT_CALLBACK_URL must use HTTPS in production")
        if self.app_env == "production" and self.payment_provider == "PAWAPAY" and self.pawapay_environment == "SANDBOX":
            raise ValueError("PawaPay sandbox payments are forbidden in production")
        if self.pawapay_api_token and "replace" in self.pawapay_api_token.get_secret_value().lower():
            raise ValueError("PAWAPAY_API_TOKEN must be a real token or be left empty")
        if self.routing_provider == "GOOGLE_MAPS" and not self.google_maps_api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY is required when ROUTING_PROVIDER is GOOGLE_MAPS")
        if self.routing_provider == "OPENROUTESERVICE" and not self.openrouteservice_api_key:
            raise ValueError(
                "OPENROUTESERVICE_API_KEY is required when ROUTING_PROVIDER is OPENROUTESERVICE"
            )
        if self.openrouteservice_api_key and "replace" in self.openrouteservice_api_key.get_secret_value().lower():
            raise ValueError("OPENROUTESERVICE_API_KEY must be a real key or be left empty")
        if self.app_env == "production" and self.storage_provider != "S3":
            raise ValueError("STORAGE_PROVIDER=S3 is required in production")
        if self.storage_provider == "S3":
            if not self.storage_bucket or not self.storage_access_key or not self.storage_secret_key:
                raise ValueError("S3 storage requires STORAGE_BUCKET, STORAGE_ACCESS_KEY and STORAGE_SECRET_KEY")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
