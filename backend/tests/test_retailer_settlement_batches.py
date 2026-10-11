from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    Base,
    Campus,
    DeliveryPoint,
    Order,
    PlatformSetting,
    Retailer,
    RetailerFulfillment,
    RetailerPayableEntry,
    RetailerSettlement,
    RetailerSettlementLine,
    User,
    University,
)
from app.services.retailer_payable_ledger import post_payable_entry
from app.services.retailer_settlement_batches import generate_retailer_settlement


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
        slug=f"retailer-{suffix}", phone="0700000000", status="ACTIVE",
    )
    order = Order(
        id=uuid4(), order_number=f"ORD-{suffix}", customer_id=customer.id,
        delivery_point_id=point.id, delivery_method="DELIVERY", currency="UGX",
        subtotal_ugx=100000, delivery_fee_ugx=2500,
        gross_delivery_fee_ugx=2500, multi_retailer_discount_ugx=0,
        multi_retailer_discount_percent=0, total_ugx=102500,
    )
    fulfillment = RetailerFulfillment(id=uuid4(), order_id=order.id, retailer_id=retailer.id)
    session.add_all([university, campus, customer, retailer_user, point, retailer, order, fulfillment])
    session.commit()
    session.add(PlatformSetting(key="retailer_settlement_policy", value={"minimum_ugx": 20000}))
    session.commit()
    return retailer, order, fulfillment


def _credit(session, retailer, order, fulfillment, amount, source):
    return post_payable_entry(
        session,
        retailer_id=retailer.id,
        order_id=order.id,
        fulfillment_id=fulfillment.id,
        entry_type="CREDIT",
        amount_ugx=amount,
        reason="approved_retailer_credit",
        source_reference=source,
    )


def test_generates_balanced_draft_at_threshold_and_reserves_entries():
    with _session() as session:
        retailer, order, fulfillment = _seed(session)
        first = _credit(session, retailer, order, fulfillment, 12000, "batch-1")
        second = _credit(session, retailer, order, fulfillment, 8000, "batch-2")

        result = generate_retailer_settlement(session, retailer_id=retailer.id)
        assert result.eligible is True
        assert result.amount_ugx == 20000
        assert result.selected_entry_count == 2
        assert result.settlement_id is not None

        settlement = session.get(RetailerSettlement, result.settlement_id)
        assert settlement.status == "DRAFT"
        assert settlement.amount_ugx == 20000
        lines = session.query(RetailerSettlementLine).filter_by(settlement_id=settlement.id).all()
        assert {line.payable_entry_id for line in lines} == {first.id, second.id}
        assert sum(line.amount_ugx for line in lines) == 20000

        second_result = generate_retailer_settlement(session, retailer_id=retailer.id)
        assert second_result.settlement_id is None
        assert second_result.reason == "below_threshold"


def test_does_not_partially_consume_a_large_payable_entry():
    with _session() as session:
        retailer, order, fulfillment = _seed(session)
        _credit(session, retailer, order, fulfillment, 25000, "large-entry")

        result = generate_retailer_settlement(session, retailer_id=retailer.id)
        assert result.settlement_id is not None
        assert result.amount_ugx == 25000
        assert result.selected_entry_count == 1


def test_failed_settlement_releases_entries_for_a_new_batch():
    with _session() as session:
        retailer, order, fulfillment = _seed(session)
        entry = _credit(session, retailer, order, fulfillment, 25000, "failed-release")

        failed = RetailerSettlement(
            id=uuid4(), retailer_id=retailer.id, amount_ugx=25000,
            currency="UGX", status="FAILED",
            settlement_reference="SET-FAILED-BATCH",
            idempotency_key="IDEMP-FAILED-BATCH",
        )
        session.add(failed)
        session.flush()
        session.add(RetailerSettlementLine(
            id=uuid4(), settlement_id=failed.id, payable_entry_id=entry.id,
            amount_ugx=25000, currency="UGX",
        ))
        session.commit()

        result = generate_retailer_settlement(session, retailer_id=retailer.id)
        assert result.settlement_id is not None
        assert result.amount_ugx == 25000


def test_recovery_blocks_new_settlement_after_debit_exceeds_paid_balance():
    with _session() as session:
        retailer, order, fulfillment = _seed(session)
        credit = _credit(session, retailer, order, fulfillment, 25000, "recovery-credit")
        settlement = generate_retailer_settlement(session, retailer_id=retailer.id)
        assert settlement.settlement_id is not None

        paid = session.get(RetailerSettlement, settlement.settlement_id)
        paid.status = "SETTLED"
        session.flush()

        session.add(
            RetailerPayableEntry(
                id=uuid4(),
                retailer_id=retailer.id,
                order_id=order.id,
                fulfillment_id=fulfillment.id,
                entry_type="DEBIT",
                amount_ugx=30000,
                currency="UGX",
                reason="refund_after_payout",
                source_reference="recovery-debit",
            )
        )
        session.commit()

        result = generate_retailer_settlement(session, retailer_id=retailer.id)
        assert result.settlement_id is None
        assert result.reason == "recovery_due"
