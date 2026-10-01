"""Application-level product media upload orchestration."""

from __future__ import annotations

from app.config import Settings, get_settings
from app.services.media_storage import MediaStorage, S3CompatibleMediaStorage


def build_media_storage(settings: Settings | None = None) -> MediaStorage | None:
    settings = settings or get_settings()
    if settings.storage_provider == "DISABLED":
        return None
    if settings.storage_provider == "S3":
        return S3CompatibleMediaStorage(
            bucket=settings.storage_bucket or "",
            access_key=settings.storage_access_key.get_secret_value() if settings.storage_access_key else "",
            secret_key=settings.storage_secret_key.get_secret_value() if settings.storage_secret_key else "",
            endpoint=settings.storage_endpoint,
            public_base_url=settings.storage_public_base_url,
        )
    raise ValueError(f"Unsupported storage provider: {settings.storage_provider}")
