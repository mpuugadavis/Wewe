import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings


SECRET = SecretStr("test-only-secret-key-that-is-at-least-32-characters")


def production_settings(**overrides):
    values = {
        "app_env": "production",
        "secret_key": SECRET,
        "database_url": "postgresql+psycopg://wewe:test@localhost/wewe",
        "rate_limit_storage_uri": "redis://localhost:6379/0",
        "smtp_host": "smtp.example.com",
        "payment_callback_url": "https://api.example.com/api/v1/payments/webhooks",
        **overrides,
    }
    return Settings(**values)


def test_production_requires_postgresql():
    with pytest.raises(ValidationError, match="DATABASE_URL must use PostgreSQL"):
        production_settings(database_url="sqlite:///./wewe.db")


def test_production_requires_shared_redis_rate_limit_storage():
    with pytest.raises(ValidationError, match="RATE_LIMIT_STORAGE_URI must use Redis"):
        production_settings(rate_limit_storage_uri="memory://")


def test_development_can_use_memory_rate_limit_storage():
    settings = Settings(
        app_env="development",
        secret_key=SECRET,
        database_url="sqlite:///./wewe.db",
        rate_limit_storage_uri="memory://",
    )
    assert settings.rate_limit_storage_uri == "memory://"


def test_production_accepts_postgresql_and_redis():
    settings = production_settings()
    assert settings.database_url.startswith("postgresql")
    assert settings.rate_limit_storage_uri.startswith("redis")
