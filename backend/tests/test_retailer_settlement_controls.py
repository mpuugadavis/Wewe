from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    Base,
    Campus,
    DeliveryPoint,
    Order,
    Retailer,
    RetailerFulfillment,
    RetailerPayableEntry,
    RetailerSettlement,
    User,
    University,
)
from app.services.retailer_payable_ledger import post_payable_entry
from app.services.retailer_settlement_controls import (
    RetailerSettlementControlError,
    SettlementEntryConflictError,
    attach_payable_entry_to_draft_settlement,
    audit_retailer_settlement,
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
        subtotal_ugx=10000, delivery_fee_ugx=2500, total_ugx=12500,
    )
    fulfillment = RetailerFulfillment(
        id=uuid4(), order_id=order.id, retailer_id=retailer.id,
    )
    session.add_all([university, campus, customer, retailer_user, point, retailer, order, fulfillment])
    session.commit()
    return retailer, order, fulfillment


def _entry(session: Session, retailer, order, fulfillment, source="capture-1"):
    return post_payable_entry(
        session,
        retailer_id=retailer.id,
        order_id=order.id,
        fulfillment_id=fulfillment.id,
        entry_type="CREDIT",
        amount_ugx=5000,
        reason="approved_retailer_credit",
        source_reference=source,
    )


def test_attach_requires_matching_retailer_and_cannot_consume_entry_twice():
    with _session() as session:
        retailer, order, fulfillment = _seed(session)
        entry = _entry(session, retailer, order, fulfillment)

        settlement = RetailerSettlement(
            id=uuid4(),
            retailer_id=retailer.id,
            amount_ugx=5000,
            currency="UGX",
            status="DRAFT",
            settlement_reference="SET-1",
            idempotency_key="SET-IDEMP-1",
        )
        session.add(settlement)
        session.commit()

        line = attach_payable_entry_to_draft_settlement(
            session,
            settlement_id=settlement.id,
            payable_entry_id=entry.id,
            amount_ugx=5000,
        )
        session.commit()

        assert line.amount_ugx == 5000

        with pytest.raises(SettlementEntryConflictError):
            attach_payable_entry_to_draft_settlement(
                session,
                settlement_id=settlement.id,
                payable_entry_id=entry.id,
                amount_ugx=5000,
            )


def test_attach_rejects_overconsumption_and_non_draft_settlement():
    with _session() as session:
        retailer, order, fulfillment = _seed(session)
        entry = _entry(session, retailer, order, fulfillment)

        settlement = RetailerSettlement(
            id=uuid4(),
            retailer_id=retailer.id,
            amount_ugx=5000,
            currency="UGX",
            status="DRAFT",
            settlement_reference="SET-2",
            idempotency_key="SET-IDEMP-2",
        )
        session.add(settlement)
        session.commit()

        with pytest.raises(SettlementEntryConflictError):
            attach_payable_entry_to_draft_settlement(
                session,
                settlement_id=settlement.id,
                payable_entry_id=entry.id,
                amount_ugx=5001,
            )

        settlement.status = "SUBMITTED"
        session.commit()

        with pytest.raises(RetailerSettlementControlError):
            attach_payable_entry_to_draft_settlement(
                session,
                settlement_id=settlement.id,
                payable_entry_id=entry.id,
                amount_ugx=5000,
            )


def test_audit_exposes_line_total_without_deciding_eligibility():
    with _session() as session:
        retailer, order, fulfillment = _seed(session)
        entry = _entry(session, retailer, order, fulfillment)

        settlement = RetailerSettlement(
            id=uuid4(),
            retailer_id=retailer.id,
            amount_ugx=5000,
            currency="UGX",
            status="DRAFT",
            settlement_reference="SET-3",
            idempotency_key="SET-IDEMP-3",
        )
        session.add(settlement)
        session.commit()

        attach_payable_entry_to_draft_settlement(
            session,
            settlement_id=settlement.id,
            payable_entry_id=entry.id,
            amount_ugx=5000,
        )
        session.commit()

        audit = audit_retailer_settlement(session, settlement.id)
        assert audit.line_count == 1
        assert audit.line_total_ugx == 5000
        assert audit.settlement_amount_ugx == 5000
        assert audit.is_balanced is True
