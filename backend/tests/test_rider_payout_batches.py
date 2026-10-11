from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, DeliveryEarning, DeliveryPayoutBatch, DeliveryPayoutBatchLine
from app.services.rider_payout_batches import (
    fail_rider_payout_batch,
    generate_rider_payout_batch,
    settle_rider_payout_batch,
    submit_rider_payout_batch,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _earning(session: Session, agent_id, amount):
    assignment_id = uuid4()
    session.add(
        DeliveryEarning(
            assignment_id=assignment_id,
            agent_id=agent_id,
            amount_ugx=amount,
            currency="UGX",
            status="PENDING",
        )
    )
    session.commit()
    return assignment_id


def test_generates_one_batch_for_all_pending_earnings():
    with _session() as session:
        agent = uuid4()
        first = _earning(session, agent, 3500)
        second = _earning(session, agent, 4500)

        result = generate_rider_payout_batch(session, agent_id=agent)

        assert result.eligible is True
        assert result.amount_ugx == 8000
        assert result.earning_count == 2
        assert result.batch_id is not None

        batch = session.get(DeliveryPayoutBatch, result.batch_id)
        assert batch.status == "DRAFT"
        lines = session.query(DeliveryPayoutBatchLine).filter_by(batch_id=batch.id).all()
        assert {line.assignment_id for line in lines} == {first, second}
        assert sum(line.amount_ugx for line in lines) == 8000

        again = generate_rider_payout_batch(session, agent_id=agent)
        assert again.batch_id is None
        assert again.reason == "no_pending_earnings"


def test_failed_batch_releases_earnings_for_retry():
    with _session() as session:
        agent = uuid4()
        assignment = _earning(session, agent, 5000)

        first = generate_rider_payout_batch(session, agent_id=agent)
        fail_rider_payout_batch(session, batch_id=first.batch_id)

        retry = generate_rider_payout_batch(session, agent_id=agent)
        assert retry.batch_id is not None
        assert retry.amount_ugx == 5000
        assert retry.earning_count == 1
        assert assignment is not None


def test_settling_batch_marks_all_earnings_paid():
    with _session() as session:
        agent = uuid4()
        first = _earning(session, agent, 3500)
        second = _earning(session, agent, 2500)

        result = generate_rider_payout_batch(session, agent_id=agent)
        submit_rider_payout_batch(session, batch_id=result.batch_id, authorized_by_user_id=uuid4())
        settled = settle_rider_payout_batch(session, batch_id=result.batch_id, payout_reference="RIDER-PAYOUT-001")

        assert settled.status == "SETTLED"
        assert session.get(DeliveryEarning, first).status == "PAID"
        assert session.get(DeliveryEarning, second).status == "PAID"
        assert session.get(DeliveryEarning, first).payout_reference == "RIDER-PAYOUT-001"


def test_review_batch_keeps_earnings_pending():
    with _session() as session:
        agent = uuid4()
        assignment = _earning(session, agent, 4000)
        result = generate_rider_payout_batch(session, agent_id=agent)

        from app.services.rider_payout_batches import review_rider_payout_batch
        review_rider_payout_batch(session, batch_id=result.batch_id)

        assert session.get(DeliveryEarning, assignment).status == "PENDING"
