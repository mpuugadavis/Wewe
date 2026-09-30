"""Reliable database-backed notification outbox dispatch.

The outbox is deliberately provider-neutral. This worker only knows how to
claim durable jobs and dispatch channels registered by the application. No
email/SMS/push provider is enabled here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import NotificationOutbox, utcnow


class NotificationHandler(Protocol):
    def __call__(self, notification: NotificationOutbox) -> None: ...


class NotificationDispatchError(Exception):
    """A retryable notification delivery failure."""


class NotificationChannelUnavailable(NotificationDispatchError):
    """Raised when no handler is configured for a channel."""


class NotificationDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, NotificationHandler] = {}

    def register(self, channel: str, handler: NotificationHandler) -> None:
        key = channel.strip().upper()
        if not key:
            raise ValueError("Notification channel cannot be empty")
        self._handlers[key] = handler

    def dispatch(self, notification: NotificationOutbox) -> None:
        handler = self._handlers.get(notification.channel.upper())
        if handler is None:
            raise NotificationChannelUnavailable(
                f"No notification handler is configured for channel {notification.channel!r}"
            )
        handler(notification)


def _in_app_handler(_notification: NotificationOutbox) -> None:
    """In-app notifications are already durable rows consumed by the API.

    The worker acknowledges the outbox record without performing an external
    side effect. Future external channels must register an idempotent handler.
    """


notification_dispatcher = NotificationDispatcher()
notification_dispatcher.register("IN_APP", _in_app_handler)


def claim_notifications(
    db: Session,
    *,
    batch_size: int = 50,
    stale_after_seconds: int = 300,
    max_attempts: int = 8,
) -> list[UUID]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if stale_after_seconds < 1:
        raise ValueError("stale_after_seconds must be positive")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")

    now = utcnow()
    stale_before = now - timedelta(seconds=stale_after_seconds)
    query = (
        select(NotificationOutbox)
        .where(
            NotificationOutbox.attempts < max_attempts,
            or_(
                and_(
                    NotificationOutbox.status.in_({"PENDING", "FAILED"}),
                    NotificationOutbox.available_at <= now,
                ),
                and_(
                    NotificationOutbox.status == "PROCESSING",
                    NotificationOutbox.locked_at.is_not(None),
                    NotificationOutbox.locked_at <= stale_before,
                ),
            ),
        )
        .order_by(NotificationOutbox.available_at.asc(), NotificationOutbox.id.asc())
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    rows = db.scalars(query).all()
    for row in rows:
        row.status = "PROCESSING"
        row.locked_at = now
        row.attempts += 1
        row.last_error = None
    db.commit()
    return [row.id for row in rows]


def _retry_delay_seconds(attempts: int) -> int:
    # 5s, 10s, 20s ... capped at 15 minutes.
    return min(900, 5 * (2 ** max(0, attempts - 1)))


def _mark_sent(db: Session, notification: NotificationOutbox) -> None:
    notification.status = "SENT"
    notification.sent_at = utcnow()
    notification.locked_at = None
    notification.last_error = None
    db.commit()


def _mark_failure(
    db: Session,
    notification: NotificationOutbox,
    error: Exception,
    *,
    max_attempts: int,
) -> None:
    now = utcnow()
    notification.locked_at = None
    notification.last_error = str(error)[:1000]
    if notification.attempts >= max_attempts:
        notification.status = "DEAD"
        notification.available_at = now
    else:
        notification.status = "FAILED"
        notification.available_at = now + timedelta(seconds=_retry_delay_seconds(notification.attempts))
    db.commit()


def process_outbox_batch(
    session_factory: Callable[[], Session],
    *,
    batch_size: int = 50,
    stale_after_seconds: int = 300,
    max_attempts: int = 8,
    dispatcher: NotificationDispatcher = notification_dispatcher,
) -> int:
    """Claim and process one bounded batch.

    Claiming and delivery are separate transactions so a slow provider never
    holds row locks. PostgreSQL workers can run concurrently because claims use
    SELECT ... FOR UPDATE SKIP LOCKED.
    """

    with session_factory() as claim_db:
        notification_ids = claim_notifications(
            claim_db,
            batch_size=batch_size,
            stale_after_seconds=stale_after_seconds,
            max_attempts=max_attempts,
        )

    processed = 0
    for notification_id in notification_ids:
        with session_factory() as db:
            notification = db.get(NotificationOutbox, notification_id)
            if notification is None or notification.status != "PROCESSING":
                continue
            try:
                dispatcher.dispatch(notification)
            except Exception as exc:
                _mark_failure(db, notification, exc, max_attempts=max_attempts)
            else:
                _mark_sent(db, notification)
            processed += 1
    return processed
