from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    Base,
    Campus,
    DeliveryPoint,
    Order,
    Payment,
    Retailer,
    RetailerFulfillment,
    RetailerPaymentAllocation,
    User,
    University,
)
from app.services.retailer_payment_allocation import (
    PaymentAllocationConflictError,
    RetailerPaymentAllocationError,
    allocate_successful_payment_to_fulfillment,
    get_payment_allocation_totals,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed(session: Session, *, payment_status="SUCCESSFUL"):
    suffix = uuid4().hex[:8]
    university = University(id=uuid4(), name=f"University {suffix}", slug=f"university-{suffix}")
    campus = Campus(id=uuid4(), university_id=university.id, name="Main", slug=f"main-{suffix}")
    customer = User(
        id=uuid4(), name="Customer", email=f"customer-{suffix}@example.com",
        password_hash="hash", role="CUSTOMER",
    )
    retailer_user = User(
        id=uuid4(), name="Retailer", email=f"retailer-{suffix}@example.com",
        password_hash="hash", role="RETAILER",
    )
    point = DeliveryPoint(id=uuid4(), campus_id=campus.id, kind="BUILDING", name="Building")
    retailer = Retailer(
        id=uuid4(), user_id=retailer_user.id, business_name=f"Retailer {suffix}",
        slug=f"retailer-{suffix}", phone="0700000000",
    )
    order = Order(
        id=uuid4(), order_number=f"ORD-{suffix}", customer_id=customer.id,
        delivery_point_id=point.id, delivery_method="DELIVERY", currency="UGX",
        subtotal_ugx=10000, delivery_fee_ugx=2000, total_ugx=12000,
    )
    fulfillment = RetailerFulfillment(
        id=uuid4(), order_id=order.id, retailer_id=retailer.id,
    )
    payment = Payment(
        id=uuid4(), order_id=order.id, customer_id=customer.id,
        amount_ugx=12000, currency="UGX", method="MTN_MOMO",
        provider="TEST_PROVIDER", status=payment_status,
    )
    session.add_all([
        university, campus, customer, retailer_user, point, retailer, order,
        fulfillment, payment,
    ])
    session.commit()
    return retailer, order, fulfillment, payment


def test_successful_payment_allocation_is_idempotent_and_bounded():
    with _session() as session:
        _, _, fulfillment, payment = _seed(session)

        first = allocate_successful_payment_to_fulfillment(
            session, payment_id=payment.id, fulfillment_id=fulfillment.id, amount_ugx=8000
        )
        session.commit()

        replay = allocate_successful_payment_to_fulfillment(
            session, payment_id=payment.id, fulfillment_id=fulfillment.id, amount_ugx=8000
        )
        assert replay.id == first.id

        totals = get_payment_allocation_totals(session, payment.id)
        assert totals.payment_amount_ugx == 12000
        assert totals.allocated_ugx == 8000
        assert totals.remaining_ugx == 4000

        with pytest.raises(PaymentAllocationConflictError):
            allocate_successful_payment_to_fulfillment(
                session, payment_id=payment.id, fulfillment_id=fulfillment.id, amount_ugx=9000
            )

        assert session.query(RetailerPaymentAllocation).count() == 1


def test_payment_cannot_be_overallocated_across_fulfillments():
    with _session() as session:
        _, order, first_fulfillment, payment = _seed(session)
        second_retailer_user = User(
            id=uuid4(), name="Second Retailer", email=f"second-{uuid4().hex}@example.com",
            password_hash="hash", role="RETAILER",
        )
        second_retailer = Retailer(
            id=uuid4(), user_id=second_retailer_user.id, business_name="Second Retailer",
            slug=f"second-{uuid4().hex[:8]}", phone="0700000001",
        )
        second_fulfillment = RetailerFulfillment(
            id=uuid4(), order_id=order.id, retailer_id=second_retailer.id,
        )
        session.add_all([second_retailer_user, second_retailer, second_fulfillment])
        session.commit()

        allocate_successful_payment_to_fulfillment(
            session, payment_id=payment.id, fulfillment_id=first_fulfillment.id, amount_ugx=9000
        )
        session.commit()

        with pytest.raises(PaymentAllocationConflictError):
            allocate_successful_payment_to_fulfillment(
                session, payment_id=payment.id, fulfillment_id=second_fulfillment.id, amount_ugx=4000
            )


def test_only_successful_online_payment_can_be_allocated():
    with _session() as session:
        _, _, fulfillment, payment = _seed(session, payment_status="PENDING")

        with pytest.raises(RetailerPaymentAllocationError):
            allocate_successful_payment_to_fulfillment(
                session, payment_id=payment.id, fulfillment_id=fulfillment.id, amount_ugx=1000
            )


def test_payment_and_fulfillment_must_belong_to_same_order():
    with _session() as session:
        _, _, fulfillment, _ = _seed(session)
        _, _, _, other_payment = _seed(session)

        with pytest.raises(PaymentAllocationConflictError):
            allocate_successful_payment_to_fulfillment(
                session, payment_id=other_payment.id, fulfillment_id=fulfillment.id, amount_ugx=1000
            )
