"""Safe product-media storage lifecycle operations.

Cleanup is deliberately conservative: only objects under the product-media
prefix that are absent from the database and older than a grace period are
eligible. Dry-run is the default at the service boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProductImage
from app.services.media_storage import MediaStorage, MediaStorageError


@dataclass(frozen=True)
class MediaCleanupCandidate:
    key: str
    last_modified: datetime | None


@dataclass(frozen=True)
class MediaCleanupResult:
    scanned: int
    candidates: int
    deleted: int
    failed: int
    keys: tuple[str, ...]


def collect_orphaned_product_media(
    db: Session,
    storage: MediaStorage,
    *,
    grace_period_seconds: int = 86_400,
    dry_run: bool = True,
    prefix: str = "products/",
    now: datetime | None = None,
) -> MediaCleanupResult:
    """Identify and optionally delete storage objects no longer referenced by ProductImage.

    Objects without a LastModified timestamp are never deleted automatically.
    The grace period protects against races with newly completed uploads and
    transactions whose database reference has not yet become visible.
    """
    if grace_period_seconds <= 0:
        raise ValueError("grace_period_seconds must be positive")
    if not prefix or not prefix.endswith("/"):
        raise ValueError("prefix must be a non-empty storage prefix ending with '/'")

    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(seconds=grace_period_seconds)

    referenced_keys = {
        key
        for key in db.scalars(
            select(ProductImage.storage_key).where(ProductImage.storage_key.is_not(None))
        ).all()
        if key
    }

    objects = storage.list_objects(prefix=prefix)
    candidates: list[MediaCleanupCandidate] = []
    for key, last_modified in objects:
        if key in referenced_keys:
            continue
        if last_modified is None:
            continue
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        if last_modified >= cutoff:
            continue
        candidates.append(MediaCleanupCandidate(key=key, last_modified=last_modified))

    if dry_run:
        return MediaCleanupResult(
            scanned=len(objects),
            candidates=len(candidates),
            deleted=0,
            failed=0,
            keys=tuple(candidate.key for candidate in candidates),
        )

    deleted = 0
    failed = 0
    for candidate in candidates:
        # Re-check immediately before deletion so a concurrently created DB
        # reference cannot be deleted based on a stale initial snapshot.
        if db.scalar(
            select(ProductImage.id).where(ProductImage.storage_key == candidate.key)
        ) is not None:
            continue
        try:
            storage.delete(key=candidate.key)
            deleted += 1
        except MediaStorageError:
            failed += 1

    return MediaCleanupResult(
        scanned=len(objects),
        candidates=len(candidates),
        deleted=deleted,
        failed=failed,
        keys=tuple(candidate.key for candidate in candidates),
    )
