from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Campus, DeliveryPoint, Order, Retailer, RetailerFulfillment, University, User
from app.services.retailer_payable_ledger import (
    PayableEntryReferenceMismatchError,
    PayableEntrySourceConflictError,
    get_retailer_payable_balance,
    post_payable_entry,
)


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_order(session: Session):
    university = University(id=uuid4(), name="Test University", slug=f"test-{uuid4().hex[:8]}")
    campus = Campus(id=uuid4(), university_id=university.id, name="Main", slug=f"main-{uuid4().hex[:8]}")
    customer = User(
        id=uuid4(),
        name="Customer",
        email=f"customer-{uuid4().hex}@example.com",
        password_hash="hash",
        role="CUSTOMER",
    )
    retailer_user = User(
        id=uuid4(),
        name="Retailer",
        email=f"retailer-{uuid4().hex}@example.com",
        password_hash="hash",
        role="RETAILER",
    )
    delivery_point = DeliveryPoint(
        id=uuid4(),
        campus_id=campus.id,
        kind="BUILDING",
        name="Test Building",
    )
    retailer = Retailer(
        id=uuid4(),
        user_id=retailer_user.id,
        business_name="Test Retailer",
        slug=f"retailer-{uuid4().hex[:8]}",
        phone="0700000000",
    )
    order = Order(
        id=uuid4(),
        order_number=f"ORD-{uuid4().hex[:12]}",
        customer_id=customer.id,
        delivery_point_id=delivery_point.id,
        delivery_method="DELIVERY",
        currency="UGX",
        subtotal_ugx=10000,
        delivery_fee_ugx=2500,
        total_ugx=12500,
    )
    fulfillment = RetailerFulfillment(
        id=uuid4(),
        order_id=order.id,
        retailer_id=retailer.id,
    )
    session.add_all([university, campus, customer, retailer_user, delivery_point, retailer, order, fulfillment])
    session.commit()
    return retailer, order, fulfillment


def test_payable_entry_is_idempotent_and_balance_is_signed():
    with _make_session() as session:
        retailer, order, fulfillment = _seed_order(session)

        first = post_payable_entry(
            session,
            retailer_id=retailer.id,
            order_id=order.id,
            fulfillment_id=fulfillment.id,
            entry_type="CREDIT",
            amount_ugx=10000,
            reason="approved_retailer_credit",
            source_reference="payment-capture-1",
        )
        session.commit()

        replay = post_payable_entry(
            session,
            retailer_id=retailer.id,
            order_id=order.id,
            fulfillment_id=fulfillment.id,
            entry_type="CREDIT",
            amount_ugx=10000,
            reason="approved_retailer_credit",
            source_reference="payment-capture-1",
        )
        assert replay.id == first.id

        post_payable_entry(
            session,
            retailer_id=retailer.id,
            order_id=order.id,
            fulfillment_id=fulfillment.id,
            entry_type="DEBIT",
            amount_ugx=1500,
            reason="approved_adjustment",
            source_reference="adjustment-1",
        )
        session.commit()

        balance = get_retailer_payable_balance(session, retailer.id)
        assert balance.credit_ugx == 10000
        assert balance.debit_ugx == 1500
        assert balance.balance_ugx == 8500


def test_source_reference_conflict_cannot_change_existing_entry():
    with _make_session() as session:
        retailer, order, fulfillment = _seed_order(session)
        post_payable_entry(
            session,
            retailer_id=retailer.id,
            order_id=order.id,
            fulfillment_id=fulfillment.id,
            entry_type="CREDIT",
            amount_ugx=10000,
            reason="approved_retailer_credit",
            source_reference="same-source",
        )
        session.commit()

        try:
            post_payable_entry(
                session,
                retailer_id=retailer.id,
                order_id=order.id,
                fulfillment_id=fulfillment.id,
                entry_type="CREDIT",
                amount_ugx=9000,
                reason="approved_retailer_credit",
                source_reference="same-source",
            )
        except PayableEntrySourceConflictError:
            pass
        else:
            raise AssertionError("expected source-reference conflict")


def test_entry_rejects_cross_fulfillment_references():
    with _make_session() as session:
        retailer, order, fulfillment = _seed_order(session)
        other_retailer, other_order, other_fulfillment = _seed_order(session)

        try:
            post_payable_entry(
                session,
                retailer_id=retailer.id,
                order_id=order.id,
                fulfillment_id=other_fulfillment.id,
                entry_type="CREDIT",
                amount_ugx=1000,
                reason="invalid_reference",
                source_reference="invalid-reference",
            )
        except PayableEntryReferenceMismatchError:
            pass
        else:
            raise AssertionError("expected reference mismatch")
