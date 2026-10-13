from datetime import timedelta

from sqlalchemy.orm import sessionmaker

from app.models import NotificationOutbox, User, utcnow
from app.services.notification_outbox import (
    NotificationDispatcher,
    claim_notifications,
    process_outbox_batch,
)


def make_user(database):
    user = User(
        name="Outbox Test User",
        email="outbox@example.com",
        password_hash="test-password-hash",
        role="CUSTOMER",
        status="ACTIVE",
    )
    database.add(user)
    database.commit()
    return user


def test_in_app_notification_is_processed_once(database):
    user = make_user(database)
    notification = NotificationOutbox(
        user_id=user.id,
        event_type="ORDER_DELIVERED",
        channel="IN_APP",
        payload={"order_id": "test-order"},
    )
    database.add(notification)
    database.commit()
    session_factory = sessionmaker(bind=database.get_bind(), autoflush=False, expire_on_commit=False)

    processed = process_outbox_batch(session_factory)

    assert processed == 1
    database.refresh(notification)
    assert notification.status == "SENT"
    assert notification.attempts == 1
    assert notification.sent_at is not None
    assert notification.last_error is None


def test_failed_notification_retries_then_dead_letters(database):
    user = make_user(database)
    notification = NotificationOutbox(
        user_id=user.id,
        event_type="EMAIL_TEST",
        channel="UNREGISTERED",
        payload={"subject": "test"},
    )
    database.add(notification)
    database.commit()
    session_factory = sessionmaker(bind=database.get_bind(), autoflush=False, expire_on_commit=False)

    dispatcher = NotificationDispatcher()
    processed = process_outbox_batch(
        session_factory,
        dispatcher=dispatcher,
        max_attempts=1,
    )

    assert processed == 1
    database.refresh(notification)
    assert notification.status == "DEAD"
    assert notification.attempts == 1
    assert "No notification handler" in notification.last_error


def test_email_notification_uses_mailer(database, monkeypatch):
    user = make_user(database)
    notification = NotificationOutbox(
        user_id=user.id,
        event_type="ORDER_READY",
        channel="EMAIL",
        payload={"to": "customer@example.com", "subject": "Order ready", "body": "Your order is ready."},
    )
    database.add(notification)
    database.commit()
    sent = []

    def fake_send_email(to_address, subject, body):
        sent.append((to_address, subject, body))

    from types import SimpleNamespace
    monkeypatch.setattr("app.services.notification_outbox.get_settings", lambda: SimpleNamespace(smtp_host="smtp.example.test"))
    monkeypatch.setattr("app.services.notification_outbox.send_email", fake_send_email)
    session_factory = sessionmaker(bind=database.get_bind(), autoflush=False, expire_on_commit=False)

    assert process_outbox_batch(session_factory) == 1
    database.refresh(notification)
    assert notification.status == "SENT"
    assert sent == [("customer@example.com", "Order ready", "Your order is ready.")]


def test_email_notification_rejects_invalid_payload(database):
    user = make_user(database)
    notification = NotificationOutbox(
        user_id=user.id,
        event_type="EMAIL_INVALID",
        channel="EMAIL",
        payload={"subject": "Missing recipient", "body": "Body"},
    )
    database.add(notification)
    database.commit()
    session_factory = sessionmaker(bind=database.get_bind(), autoflush=False, expire_on_commit=False)

    assert process_outbox_batch(session_factory, max_attempts=1) == 1
    database.refresh(notification)
    assert notification.status == "DEAD"
    assert "requires a non-empty 'to' address" in notification.last_error


def test_stale_processing_job_is_reclaimed(database):
    user = make_user(database)
    notification = NotificationOutbox(
        user_id=user.id,
        event_type="ORDER_READY",
        channel="IN_APP",
        payload={},
        status="PROCESSING",
        attempts=1,
        locked_at=utcnow() - timedelta(minutes=10),
        available_at=utcnow() - timedelta(minutes=10),
    )
    database.add(notification)
    database.commit()

    claimed = claim_notifications(database, batch_size=10, stale_after_seconds=300)

    assert claimed == [notification.id]
    database.refresh(notification)
    assert notification.status == "PROCESSING"
    assert notification.attempts == 2
    assert notification.locked_at is not None


def test_future_failed_job_is_not_claimed(database):
    user = make_user(database)
    notification = NotificationOutbox(
        user_id=user.id,
        event_type="EMAIL_RETRY",
        channel="EMAIL",
        payload={},
        status="FAILED",
        attempts=1,
        available_at=utcnow() + timedelta(minutes=5),
    )
    database.add(notification)
    database.commit()

    assert claim_notifications(database) == []
    database.refresh(notification)
    assert notification.status == "FAILED"
    assert notification.attempts == 1


def test_stale_job_at_attempt_limit_is_dead_lettered(database):
    user = make_user(database)
    notification = NotificationOutbox(
        user_id=user.id,
        event_type="ORDER_READY",
        channel="IN_APP",
        payload={},
        status="PROCESSING",
        attempts=8,
        locked_at=utcnow() - timedelta(minutes=10),
        available_at=utcnow() - timedelta(minutes=10),
    )
    database.add(notification)
    database.commit()

    claimed = claim_notifications(database, batch_size=10, stale_after_seconds=300, max_attempts=8)

    assert claimed == []
    database.refresh(notification)
    assert notification.status == "DEAD"
    assert notification.locked_at is None
