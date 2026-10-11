"""Controlled rider payout batch generation and lifecycle."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import DeliveryEarning, DeliveryPayoutBatch, DeliveryPayoutBatchLine, utcnow


ACTIVE_BATCH_STATUSES = ("DRAFT", "SUBMITTED", "REVIEW_REQUIRED")


class RiderPayoutBatchError(RuntimeError):
    pass


class RiderPayoutNotFoundError(RiderPayoutBatchError):
    pass


@dataclass(frozen=True, slots=True)
class RiderPayoutBatchResult:
    agent_id: UUID
    batch_id: UUID | None
    amount_ugx: int
    earning_count: int
    eligible: bool
    reason: str | None = None


def generate_rider_payout_batch(
    session: Session,
    *,
    agent_id: UUID,
) -> RiderPayoutBatchResult:
    earnings = session.scalars(
        select(DeliveryEarning)
        .where(
            DeliveryEarning.agent_id == agent_id,
            DeliveryEarning.status == "PENDING",
            ~exists(
                select(DeliveryPayoutBatchLine.id)
                .join(DeliveryPayoutBatch, DeliveryPayoutBatch.id == DeliveryPayoutBatchLine.batch_id)
                .where(
                    DeliveryPayoutBatchLine.assignment_id == DeliveryEarning.assignment_id,
                    DeliveryPayoutBatch.status.in_(ACTIVE_BATCH_STATUSES),
                )
            ),
        )
        .order_by(DeliveryEarning.created_at.asc(), DeliveryEarning.assignment_id.asc())
        .with_for_update()
    ).all()

    if not earnings:
        return RiderPayoutBatchResult(agent_id, None, 0, 0, False, "no_pending_earnings")

    total = sum(int(row.amount_ugx) for row in earnings)
    batch = DeliveryPayoutBatch(
        agent_id=agent_id,
        amount_ugx=total,
        currency="UGX",
        status="DRAFT",
        batch_reference=f"RID-PAY-{uuid4().hex[:20].upper()}",
        idempotency_key=f"rider-payout:{uuid4()}",
    )
    session.add(batch)
    session.flush()

    for earning in earnings:
        session.add(
            DeliveryPayoutBatchLine(
                batch_id=batch.id,
                assignment_id=earning.assignment_id,
                amount_ugx=earning.amount_ugx,
                currency="UGX",
            )
        )

    session.flush()
    return RiderPayoutBatchResult(agent_id, batch.id, total, len(earnings), True)


def generate_rider_payout_batches(
    session: Session,
    *,
    agent_id: UUID | None = None,
    limit: int = 100,
) -> list[RiderPayoutBatchResult]:
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")

    if agent_id is not None:
        return [generate_rider_payout_batch(session, agent_id=agent_id)]

    agent_ids = session.scalars(
        select(DeliveryEarning.agent_id)
        .where(DeliveryEarning.status == "PENDING")
        .distinct()
        .order_by(DeliveryEarning.agent_id)
        .limit(limit)
    ).all()
    return [generate_rider_payout_batch(session, agent_id=row) for row in agent_ids]


def _get_batch(session: Session, batch_id: UUID) -> DeliveryPayoutBatch:
    batch = session.scalar(
        select(DeliveryPayoutBatch).where(DeliveryPayoutBatch.id == batch_id).with_for_update()
    )
    if batch is None:
        raise RiderPayoutNotFoundError("Rider payout batch was not found.")
    return batch


def submit_rider_payout_batch(session: Session, *, batch_id: UUID, authorized_by_user_id: UUID) -> DeliveryPayoutBatch:
    batch = _get_batch(session, batch_id)
    if batch.status != "DRAFT":
        raise RiderPayoutBatchError("Only DRAFT rider payout batches can be submitted.")
    lines = session.scalars(select(DeliveryPayoutBatchLine).where(DeliveryPayoutBatchLine.batch_id == batch.id)).all()
    if not lines or sum(line.amount_ugx for line in lines) != batch.amount_ugx:
        raise RiderPayoutBatchError("Rider payout batch lines must exactly balance the batch.")
    batch.status = "SUBMITTED"
    batch.authorized_by_user_id = authorized_by_user_id
    batch.submitted_at = utcnow()
    session.flush()
    return batch


def settle_rider_payout_batch(session: Session, *, batch_id: UUID, payout_reference: str) -> DeliveryPayoutBatch:
    batch = _get_batch(session, batch_id)
    if batch.status != "SUBMITTED":
        raise RiderPayoutBatchError("Only SUBMITTED rider payout batches can be marked settled.")
    if not payout_reference.strip():
        raise RiderPayoutBatchError("A payout reference is required.")
    lines = session.scalars(select(DeliveryPayoutBatchLine).where(DeliveryPayoutBatchLine.batch_id == batch.id).with_for_update()).all()
    for line in lines:
        earning = session.get(DeliveryEarning, line.assignment_id, with_for_update=True)
        if earning is None or earning.status != "PENDING":
            raise RiderPayoutBatchError("A payout line is no longer pending.")
        earning.status = "PAID"
        earning.payout_reference = payout_reference
        earning.paid_at = utcnow()
    batch.status = "SETTLED"
    batch.payout_reference = payout_reference
    batch.settled_at = utcnow()
    session.flush()
    return batch


def fail_rider_payout_batch(session: Session, *, batch_id: UUID) -> DeliveryPayoutBatch:
    batch = _get_batch(session, batch_id)
    if batch.status != "SUBMITTED":
        raise RiderPayoutBatchError("Only SUBMITTED rider payout batches can be marked failed.")
    batch.status = "FAILED"
    session.flush()
    return batch


def review_rider_payout_batch(session: Session, *, batch_id: UUID) -> DeliveryPayoutBatch:
    batch = _get_batch(session, batch_id)
    if batch.status not in {"DRAFT", "SUBMITTED"}:
        raise RiderPayoutBatchError("Only DRAFT or SUBMITTED batches can require review.")
    batch.status = "REVIEW_REQUIRED"
    session.flush()
    return batch
