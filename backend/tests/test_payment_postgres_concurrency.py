import os
import threading
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import Campus, DeliveryPoint, Order, Payment, University, User


pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def postgres_engine():
    if os.getenv("RUN_POSTGRES_CONCURRENCY") != "1":
        pytest.skip("PostgreSQL concurrency verification is enabled only in the PostgreSQL CI job.")
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL.")
    engine = create_engine(url, pool_pre_ping=True)
    yield engine
    engine.dispose()


def test_order_row_lock_allows_only_one_active_payment_attempt(postgres_engine) -> None:
    SessionLocal = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    owner_session = SessionLocal()

    suffix = uuid4().hex[:10]
    university = University(name=f"Concurrency University {suffix}", slug=f"concurrency-university-{suffix}", country_code="UG")
    owner = User(
        name="Concurrency Customer",
        email=f"concurrency-{suffix}@example.test",
        phone=f"+2567000{suffix[:6]}",
        password_hash="test-hash",
        role="CUSTOMER",
        status="ACTIVE",
    )
    owner_session.add_all([university, owner])
    owner_session.flush()

    campus = Campus(university_id=university.id, name=f"Concurrency Campus {suffix}", slug=f"concurrency-campus-{suffix}")
    owner_session.add(campus)
    owner_session.flush()

    point = DeliveryPoint(
        campus_id=campus.id,
        owner_user_id=owner.id,
        kind="ROOM",
        name=f"Concurrency Room {suffix}",
        is_private=True,
    )
    owner_session.add(point)
    owner_session.flush()

    order = Order(
        order_number=f"CON-{suffix}",
        customer_id=owner.id,
        delivery_point_id=point.id,
        delivery_method="DELIVERY",
        currency="UGX",
        subtotal_ugx=10000,
        delivery_fee_ugx=2500,
        total_ugx=12500,
        status="PENDING",
        payment_status="UNPAID",
    )
    owner_session.add(order)
    owner_session.commit()
    order_id = order.id
    campus_id = campus.id
    owner_session.close()

    first_locked = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_finished = threading.Event()
    second_observed_active = []
    errors = []

    def first_transaction() -> None:
        session = SessionLocal()
        try:
            locked = session.scalar(
                select(Order).where(Order.id == order_id).with_for_update()
            )
            assert locked is not None
            existing = session.scalar(
                select(Payment.id).where(
                    Payment.order_id == locked.id,
                    Payment.status.in_(["PENDING", "UNKNOWN", "SUCCESSFUL"]),
                )
            )
            assert existing is None
            session.add(
                Payment(
                    order_id=locked.id,
                    customer_id=locked.customer_id,
                    amount_ugx=locked.total_ugx,
                    currency="UGX",
                    method="MTN_MOMO",
                    provider="MTN_MOMO",
                    status="PENDING",
                )
            )
            locked.payment_status = "PENDING"
            session.flush()
            first_locked.set()
            assert release_first.wait(timeout=5)
            session.commit()
        except Exception as exc:
            errors.append(exc)
            session.rollback()
        finally:
            session.close()

    def second_transaction() -> None:
        session = SessionLocal()
        try:
            second_started.set()
            locked = session.scalar(
                select(Order).where(Order.id == order.id).with_for_update()
            )
            assert locked is not None
            existing = session.scalar(
                select(Payment.id).where(
                    Payment.order_id == locked.id,
                    Payment.status.in_(["PENDING", "UNKNOWN", "SUCCESSFUL"]),
                )
            )
            second_observed_active.append(existing is not None)
            session.rollback()
        except Exception as exc:
            errors.append(exc)
            session.rollback()
        finally:
            second_finished.set()
            session.close()

    first = threading.Thread(target=first_transaction, daemon=True)
    second = threading.Thread(target=second_transaction, daemon=True)

    first.start()
    assert first_locked.wait(timeout=5)

    second.start()
    assert second_started.wait(timeout=5)

    # The second transaction must remain blocked on the same order row until
    # the first transaction commits. A short polling window avoids relying on
    # an exact scheduler sleep.
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not second_finished.is_set():
        time.sleep(0.02)
    assert not second_finished.is_set()

    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not errors
    assert second_finished.is_set()
    assert second_observed_active == [True]

    cleanup = SessionLocal()
    try:
        cleanup.execute(
            Payment.__table__.delete().where(Payment.order_id == order_id)
        )
        cleanup_order = cleanup.get(Order, order_id)
        assert cleanup_order is not None
        cleanup.delete(cleanup_order)
        cleanup.execute(delete(DeliveryPoint).where(DeliveryPoint.id == point.id))
        cleanup.execute(delete(Campus).where(Campus.id == campus_id))
        cleanup.delete(owner)
        cleanup.delete(university)
        cleanup.commit()
    finally:
        cleanup.close()
