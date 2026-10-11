from uuid import uuid4

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
    RetailerSettlementLine,
    User,
    University,
)
from app.services.retailer_income import (
    DEFAULT_RETAILER_SETTLEMENT_THRESHOLD_UGX,
    get_retailer_income_snapshot,
    retailer_income_payload,
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
        slug=f"retailer-{suffix}", phone="+256700000000",
    )
    order = Order(
        id=uuid4(), order_number=f"ORD-{suffix}", customer_id=customer.id,
        delivery_point_id=point.id, delivery_method="DELIVERY", currency="UGX",
        subtotal_ugx=25000, delivery_fee_ugx=2500, gross_delivery_fee_ugx=2500,
        multi_retailer_discount_ugx=0, multi_retailer_discount_percent=0,
        total_ugx=27500,
    )
    fulfillment = RetailerFulfillment(id=uuid4(), order_id=order.id, retailer_id=retailer.id)
    session.add_all([university, campus, customer, retailer_user, point, retailer, order, fulfillment])
    session.commit()
    return retailer, order, fulfillment


def _entry(session, retailer, order, fulfillment, amount, source, entry_type="CREDIT"):
    entry = RetailerPayableEntry(
        id=uuid4(),
        retailer_id=retailer.id,
        order_id=order.id,
        fulfillment_id=fulfillment.id,
        entry_type=entry_type,
        amount_ugx=amount,
        currency="UGX",
        reason="approved_retailer_credit" if entry_type == "CREDIT" else "refund_reversal",
        source_reference=source,
    )
    session.add(entry)
    session.flush()
    return entry


def test_default_retailer_tracker_reports_owed_and_threshold():
    with _session() as session:
        retailer, order, fulfillment = _seed(session)
        _entry(session, retailer, order, fulfillment, 25_000, "credit-1")
        session.commit()

        snapshot = get_retailer_income_snapshot(session, retailer.id)

        assert snapshot.ledger_balance_ugx == 25_000
        assert snapshot.owed_by_wewe_ugx == 25_000
        assert snapshot.paid_out_ugx == 0
        assert snapshot.pending_payout_ugx == 0
        assert snapshot.available_to_settle_ugx == 25_000
        assert snapshot.minimum_settlement_ugx == DEFAULT_RETAILER_SETTLEMENT_THRESHOLD_UGX
        assert snapshot.eligible_for_settlement is True


def test_pending_settlement_is_reserved_but_failed_settlement_releases_it():
    with _session() as session:
        retailer, order, fulfillment = _seed(session)
        entry = _entry(session, retailer, order, fulfillment, 30_000, "credit-2")

        pending = RetailerSettlement(
            id=uuid4(), retailer_id=retailer.id, amount_ugx=30_000, currency="UGX",
            status="SUBMITTED", settlement_reference="SET-SUBMITTED",
            idempotency_key="IDEMP-SUBMITTED",
        )
        failed = RetailerSettlement(
            id=uuid4(), retailer_id=retailer.id, amount_ugx=0, currency="UGX",
            status="FAILED", settlement_reference="SET-FAILED",
            idempotency_key="IDEMP-FAILED",
        )
        session.add_all([pending, failed])
        session.flush()
        session.add(RetailerSettlementLine(
            id=uuid4(), settlement_id=pending.id, payable_entry_id=entry.id,
            amount_ugx=30_000, currency="UGX",
        ))
        session.commit()

        snapshot = get_retailer_income_snapshot(session, retailer.id)
        assert snapshot.owed_by_wewe_ugx == 30_000
        assert snapshot.pending_payout_ugx == 30_000
        assert snapshot.available_to_settle_ugx == 0
        assert snapshot.eligible_for_settlement is False


def test_settled_payout_reduces_amount_wewe_owes():
    with _session() as session:
        retailer, order, fulfillment = _seed(session)
        entry = _entry(session, retailer, order, fulfillment, 40_000, "credit-3")
        settlement = RetailerSettlement(
            id=uuid4(), retailer_id=retailer.id, amount_ugx=40_000, currency="UGX",
            status="SETTLED", settlement_reference="SET-SETTLED",
            idempotency_key="IDEMP-SETTLED", payout_reference="PAYOUT-1",
        )
        session.add(settlement)
        session.flush()
        session.add(RetailerSettlementLine(
            id=uuid4(), settlement_id=settlement.id, payable_entry_id=entry.id,
            amount_ugx=40_000, currency="UGX",
        ))
        session.commit()

        snapshot = get_retailer_income_snapshot(session, retailer.id)
        assert snapshot.owed_by_wewe_ugx == 0
        assert snapshot.paid_out_ugx == 40_000
        assert snapshot.available_to_settle_ugx == 0


def test_refund_debit_after_payout_creates_recovery_due():
    with _session() as session:
        retailer, order, fulfillment = _seed(session)
        _entry(session, retailer, order, fulfillment, 20_000, "credit-4")
        _entry(session, retailer, order, fulfillment, 20_000, "debit-4", "DEBIT")
        settlement = RetailerSettlement(
            id=uuid4(), retailer_id=retailer.id, amount_ugx=20_000, currency="UGX",
            status="SETTLED", settlement_reference="SET-RECOVERY",
            idempotency_key="IDEMP-RECOVERY", payout_reference="PAYOUT-2",
        )
        session.add(settlement)
        session.commit()

        snapshot = get_retailer_income_snapshot(session, retailer.id)
        assert snapshot.ledger_balance_ugx == 0
        assert snapshot.recovery_due_ugx == 20_000
        assert snapshot.owed_by_wewe_ugx == 0
        assert snapshot.eligible_for_settlement is False


def test_payload_contains_dashboard_ready_history():
    with _session() as session:
        retailer, order, fulfillment = _seed(session)
        _entry(session, retailer, order, fulfillment, 22_000, "credit-5")
        session.commit()

        payload = retailer_income_payload(session, retailer.id)

        assert payload["currency"] == "UGX"
        assert payload["owed_by_wewe_ugx"] == 22_000
        assert payload["eligible_for_settlement"] is True
        assert len(payload["entries"]) == 1
        assert payload["settlements"] == []
