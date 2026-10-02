from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Campus, DeliveryPoint, Order, Retailer, RetailerFulfillment, User, University
from app.services.retailer_payable_ledger import post_payable_entry
from app.services.retailer_settlement_controls import attach_payable_entry_to_draft_settlement
from app.services.retailer_settlement_operations import (
    SettlementIdempotencyConflictError,
    SettlementLifecycleConflictError,
    create_draft_settlement,
    mark_settlement_failed,
    mark_settlement_review_required,
    mark_settlement_settled,
    settlement_snapshot,
    submit_settlement,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed(session: Session):
    suffix = uuid4().hex[:8]
    university = University(id=uuid4(), name=f"University {suffix}", slug=f"university-{suffix}")
    campus = Campus(id=uuid4(), university_id=university.id, name="Main", slug=f"main-{suffix}")
    customer = User(id=uuid4(), name="Customer", email=f"customer-{suffix}@example.com", password_hash="hash", role="CUSTOMER")
    retailer_user = User(id=uuid4(), name="Retailer", email=f"retailer-{suffix}@example.com", password_hash="hash", role="RETAILER")
    point = DeliveryPoint(id=uuid4(), campus_id=campus.id, kind="BUILDING", name="Building")
    retailer = Retailer(id=uuid4(), user_id=retailer_user.id, business_name=f"Retailer {suffix}", slug=f"retailer-{suffix}", phone="0700000000")
    order = Order(
        id=uuid4(), order_number=f"ORD-{suffix}", customer_id=customer.id,
        delivery_point_id=point.id, delivery_method="DELIVERY", currency="UGX",
        subtotal_ugx=10000, delivery_fee_ugx=2500, total_ugx=12500,
    )
    fulfillment = RetailerFulfillment(id=uuid4(), order_id=order.id, retailer_id=retailer.id)
    session.add_all([university, campus, customer, retailer_user, point, retailer, order, fulfillment])
    session.commit()
    return retailer, order, fulfillment, retailer_user


def _credit(session, retailer, order, fulfillment):
    return post_payable_entry(
        session,
        retailer_id=retailer.id,
        order_id=order.id,
        fulfillment_id=fulfillment.id,
        entry_type="CREDIT",
        amount_ugx=5000,
        reason="approved_retailer_credit",
        source_reference=f"capture-{uuid4().hex}",
    )


def _draft(session, retailer, reference="SET-1", key="IDEMP-1"):
    return create_draft_settlement(
        session,
        retailer_id=retailer.id,
        amount_ugx=5000,
        settlement_reference=reference,
        idempotency_key=key,
    )


def test_draft_creation_is_idempotent_and_conflicts_on_changed_data():
    with _session() as session:
        retailer, order, fulfillment, _ = _seed(session)
        first = _draft(session, retailer)
        second = _draft(session, retailer)
        assert first.id == second.id
        assert second.status == "DRAFT"

        with pytest.raises(SettlementIdempotencyConflictError):
            create_draft_settlement(
                session, retailer_id=retailer.id, amount_ugx=6000,
                settlement_reference="SET-OTHER", idempotency_key="IDEMP-1",
            )


def test_submit_requires_exactly_balanced_lines():
    with _session() as session:
        retailer, order, fulfillment, admin_user = _seed(session)
        settlement = _draft(session, retailer)
        with pytest.raises(SettlementLifecycleConflictError):
            submit_settlement(session, settlement_id=settlement.id, authorized_by_user_id=admin_user.id)

        entry = _credit(session, retailer, order, fulfillment)
        attach_payable_entry_to_draft_settlement(
            session, settlement_id=settlement.id, payable_entry_id=entry.id, amount_ugx=5000,
        )
        session.commit()

        submitted = submit_settlement(session, settlement_id=settlement.id, authorized_by_user_id=admin_user.id)
        assert submitted.status == "SUBMITTED"
        assert submitted.authorized_by_user_id == admin_user.id
        assert submitted.submitted_at is not None


def test_settlement_completion_requires_submitted_state_and_payout_reference():
    with _session() as session:
        retailer, _, _, _ = _seed(session)
        settlement = _draft(session, retailer)

        with pytest.raises(SettlementLifecycleConflictError):
            mark_settlement_settled(session, settlement_id=settlement.id, payout_reference="PAY-1")

        with pytest.raises(SettlementLifecycleConflictError):
            mark_settlement_failed(session, settlement_id=settlement.id)

        mark_settlement_review_required(session, settlement_id=settlement.id)
        assert settlement.status == "REVIEW_REQUIRED"

        settlement.status = "SUBMITTED"
        session.commit()
        settled = mark_settlement_settled(session, settlement_id=settlement.id, payout_reference="PAY-1")
        assert settled.status == "SETTLED"
        assert settled.payout_reference == "PAY-1"
        assert settled.settled_at is not None


def test_snapshot_reports_balance_without_inventing_policy():
    with _session() as session:
        retailer, order, fulfillment, _ = _seed(session)
        settlement = _draft(session, retailer)
        entry = _credit(session, retailer, order, fulfillment)
        attach_payable_entry_to_draft_settlement(
            session, settlement_id=settlement.id, payable_entry_id=entry.id, amount_ugx=5000,
        )
        session.commit()
        snapshot = settlement_snapshot(session, settlement.id)
        assert snapshot.line_count == 1
        assert snapshot.line_total_ugx == 5000
        assert snapshot.amount_ugx == 5000
        assert snapshot.is_balanced is True
