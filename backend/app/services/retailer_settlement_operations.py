"""Technical settlement lifecycle operations.

This module deliberately contains no commercial eligibility, cadence, threshold,
commission, fee, tax, or payout-policy decisions. It only enforces the lifecycle
and integrity of an explicitly created settlement instruction.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models import RetailerPayableEntry, RetailerSettlement, RetailerSettlementLine, utcnow
from app.services.retailer_settlement_controls import audit_retailer_settlement


class RetailerSettlementOperationError(RuntimeError):
    """Base error for technical settlement lifecycle operations."""


class SettlementIdempotencyConflictError(RetailerSettlementOperationError):
    pass


class SettlementLifecycleConflictError(RetailerSettlementOperationError):
    pass


@dataclass(frozen=True)
class SettlementSnapshot:
    id: UUID
    retailer_id: UUID
    amount_ugx: int
    currency: str
    status: str
    settlement_reference: str
    idempotency_key: str
    payout_reference: str | None
    authorized_by_user_id: UUID | None
    submitted_at: object | None
    settled_at: object | None
    line_count: int
    line_total_ugx: int
    is_balanced: bool


def create_draft_settlement(
    session: Session,
    *,
    retailer_id: UUID,
    amount_ugx: int,
    settlement_reference: str,
    idempotency_key: str,
) -> RetailerSettlement:
    if amount_ugx <= 0:
        raise SettlementLifecycleConflictError("Settlement amount must be positive.")
    if not settlement_reference.strip() or not idempotency_key.strip():
        raise SettlementLifecycleConflictError("Settlement reference and idempotency key are required.")

    existing = session.scalar(
        select(RetailerSettlement)
        .where(RetailerSettlement.idempotency_key == idempotency_key)
        .with_for_update()
    )
    if existing is not None:
        if (
            existing.retailer_id != retailer_id
            or existing.amount_ugx != amount_ugx
            or existing.settlement_reference != settlement_reference
        ):
            raise SettlementIdempotencyConflictError(
                "The settlement idempotency key is already bound to different settlement data."
            )
        return existing

    settlement = RetailerSettlement(
        retailer_id=retailer_id,
        amount_ugx=amount_ugx,
        currency="UGX",
        status="DRAFT",
        settlement_reference=settlement_reference,
        idempotency_key=idempotency_key,
    )
    session.add(settlement)
    session.flush()
    return settlement


def submit_settlement(
    session: Session,
    *,
    settlement_id: UUID,
    authorized_by_user_id: UUID,
) -> RetailerSettlement:
    settlement = session.scalar(
        select(RetailerSettlement).where(RetailerSettlement.id == settlement_id).with_for_update()
    )
    if settlement is None:
        raise SettlementLifecycleConflictError("Settlement was not found.")
    if settlement.status != "DRAFT":
        raise SettlementLifecycleConflictError("Only DRAFT settlements can be submitted.")

    audit = audit_retailer_settlement(session, settlement.id)
    if not audit.is_balanced:
        raise SettlementLifecycleConflictError(
            "Settlement lines must exactly balance the settlement amount before submission."
        )

    settlement.status = "SUBMITTED"
    settlement.authorized_by_user_id = authorized_by_user_id
    settlement.submitted_at = utcnow()
    session.flush()
    return settlement


def mark_settlement_settled(
    session: Session,
    *,
    settlement_id: UUID,
    payout_reference: str,
) -> RetailerSettlement:
    settlement = session.scalar(
        select(RetailerSettlement).where(RetailerSettlement.id == settlement_id).with_for_update()
    )
    if settlement is None:
        raise SettlementLifecycleConflictError("Settlement was not found.")
    if settlement.status != "SUBMITTED":
        raise SettlementLifecycleConflictError("Only SUBMITTED settlements can be marked settled.")
    if not payout_reference.strip():
        raise SettlementLifecycleConflictError("A payout reference is required to mark a settlement settled.")

    settlement.status = "SETTLED"
    settlement.payout_reference = payout_reference
    settlement.settled_at = utcnow()
    session.flush()
    return settlement


def mark_settlement_review_required(
    session: Session,
    *,
    settlement_id: UUID,
) -> RetailerSettlement:
    settlement = session.scalar(
        select(RetailerSettlement).where(RetailerSettlement.id == settlement_id).with_for_update()
    )
    if settlement is None:
        raise SettlementLifecycleConflictError("Settlement was not found.")
    if settlement.status not in {"DRAFT", "SUBMITTED"}:
        raise SettlementLifecycleConflictError(
            "Only DRAFT or SUBMITTED settlements can be moved to review."
        )
    settlement.status = "REVIEW_REQUIRED"
    session.flush()
    return settlement


def mark_settlement_failed(
    session: Session,
    *,
    settlement_id: UUID,
) -> RetailerSettlement:
    settlement = session.scalar(
        select(RetailerSettlement).where(RetailerSettlement.id == settlement_id).with_for_update()
    )
    if settlement is None:
        raise SettlementLifecycleConflictError("Settlement was not found.")
    if settlement.status != "SUBMITTED":
        raise SettlementLifecycleConflictError("Only SUBMITTED settlements can be marked failed.")
    settlement.status = "FAILED"
    session.flush()
    return settlement


def settlement_snapshot(session: Session, settlement_id: UUID) -> SettlementSnapshot:
    settlement = session.get(RetailerSettlement, settlement_id)
    if settlement is None:
        raise SettlementLifecycleConflictError("Settlement was not found.")
    audit = audit_retailer_settlement(session, settlement.id)
    return SettlementSnapshot(
        id=settlement.id,
        retailer_id=settlement.retailer_id,
        amount_ugx=settlement.amount_ugx,
        currency=settlement.currency,
        status=settlement.status,
        settlement_reference=settlement.settlement_reference,
        idempotency_key=settlement.idempotency_key,
        payout_reference=settlement.payout_reference,
        authorized_by_user_id=settlement.authorized_by_user_id,
        submitted_at=settlement.submitted_at,
        settled_at=settlement.settled_at,
        line_count=audit.line_count,
        line_total_ugx=audit.line_total_ugx,
        is_balanced=audit.is_balanced,
    )


def list_retailer_settlements(
    session: Session,
    *,
    retailer_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[SettlementSnapshot]:
    rows = session.scalars(
        select(RetailerSettlement)
        .where(RetailerSettlement.retailer_id == retailer_id)
        .order_by(RetailerSettlement.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [settlement_snapshot(session, row.id) for row in rows]
