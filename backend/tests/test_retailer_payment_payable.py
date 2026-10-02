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
    RetailerPayableEntry,
    RetailerPaymentAllocation,
    University,
    User,
)
from app.services.retailer_payment_allocation import (
    allocate_successful_payment_to_fulfillment,
)
from app.services.retailer_payment_payable import (
    PaymentAllocationPayableLinkError,
    post_payable_credit_for_payment_allocation,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed(session: Session):
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
        provider="TEST_PROVIDER", status="SUCCESSFUL",
    )
    session.add_all([
        university, campus, customer, retailer_user, point, retailer, order,
        fulfillment, payment,
    ])
    session.commit()
    return retailer, order, fulfillment, payment


def test_allocation_posts_exact_credit_and_is_idempotent():
    with _session() as session:
        retailer, order, fulfillment, payment = _seed(session)
        allocation = allocate_successful_payment_to_fulfillment(
            session,
            payment_id=payment.id,
            fulfillment_id=fulfillment.id,
            amount_ugx=8000,
        )
        session.commit()

        first = post_payable_credit_for_payment_allocation(
            session, allocation_id=allocation.id
        )
        session.commit()

        replay = post_payable_credit_for_payment_allocation(
            session, allocation_id=allocation.id
        )
        assert replay.id == first.id

        entry = session.get(RetailerPayableEntry, first.id)
        assert entry is not None
        assert entry.retailer_id == retailer.id
        assert entry.order_id == order.id
        assert entry.fulfillment_id == fulfillment.id
        assert entry.payment_id == payment.id
        assert entry.entry_type == "CREDIT"
        assert entry.amount_ugx == 8000
        assert entry.source_reference == f"payment-allocation:{allocation.id}"
        assert entry.metadata_json == {"payment_allocation_id": str(allocation.id)}
        assert session.query(RetailerPayableEntry).count() == 1


def test_link_does_not_derive_credit_from_payment_total_or_delivery_fee():
    with _session() as session:
        _, _, fulfillment, payment = _seed(session)
        allocation = allocate_successful_payment_to_fulfillment(
            session,
            payment_id=payment.id,
            fulfillment_id=fulfillment.id,
            amount_ugx=7000,
        )
        session.commit()

        entry = post_payable_credit_for_payment_allocation(
            session, allocation_id=allocation.id
        )

        assert entry.amount_ugx == 7000
        assert entry.amount_ugx != payment.amount_ugx


def test_missing_allocation_is_rejected():
    with _session() as session:
        with pytest.raises(PaymentAllocationPayableLinkError):
            post_payable_credit_for_payment_allocation(
                session, allocation_id=uuid4()
            )


