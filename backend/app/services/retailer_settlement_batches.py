"""Generate retailer settlement batches from the immutable payable ledger.

Commercial policy is read from platform settings; this service only creates DRAFT
settlement instructions. It never submits or marks a payout as successful.

Concurrency rule: lock the retailer row first, then inspect/consume unreserved
payable credits. This serializes batch generation for one retailer and prevents
two concurrent generators from selecting the same credits.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.models import Retailer, RetailerPayableEntry, RetailerSettlement, RetailerSettlementLine
from app.services.retailer_income import (
    RetailerIncomeError,
    get_retailer_income_snapshot,
    resolve_retailer_settlement_threshold,
)
from app.services.retailer_settlement_controls import attach_payable_entry_to_draft_settlement
from app.services.retailer_settlement_operations import create_draft_settlement


ACTIVE_SETTLEMENT_STATUSES = ("DRAFT", "SUBMITTED", "SETTLED")


class RetailerSettlementBatchError(RuntimeError):
    """Base error for automatic retailer settlement generation."""


class RetailerNotFoundError(RetailerSettlementBatchError):
    pass


class RetailerRecoveryRequiredError(RetailerSettlementBatchError):
    pass


@dataclass(frozen=True, slots=True)
class SettlementBatchResult:
    retailer_id: UUID
    settlement_id: UUID | None
    amount_ugx: int
    threshold_ugx: int
    selected_entry_count: int
    eligible: bool
    reason: str | None = None


def _unconsumed_credit_statement(session: Session, retailer_id: UUID):
    active_line = exists(
        select(RetailerSettlementLine.id)
        .join(RetailerSettlement, RetailerSettlement.id == RetailerSettlementLine.settlement_id)
        .where(
            RetailerSettlementLine.payable_entry_id == RetailerPayableEntry.id,
            RetailerSettlement.status.in_(ACTIVE_SETTLEMENT_STATUSES),
        )
    )
    return (
        select(RetailerPayableEntry)
        .where(
            RetailerPayableEntry.retailer_id == retailer_id,
            RetailerPayableEntry.entry_type == "CREDIT",
            ~active_line,
        )
        .order_by(RetailerPayableEntry.created_at.asc(), RetailerPayableEntry.id.asc())
        .with_for_update()
    )


def generate_retailer_settlement(
    session: Session,
    *,
    retailer_id: UUID,
) -> SettlementBatchResult:
    """Create one balanced DRAFT settlement when the retailer is eligible.

    A payable entry is never partially consumed. This is intentional: the
    current ledger contract requires each settlement line to consume a whole
    payable credit. A later partial-settlement feature can add allocation
    records without weakening this invariant.
    """

    retailer = session.scalar(
        select(Retailer).where(Retailer.id == retailer_id).with_for_update()
    )
    if retailer is None:
        raise RetailerNotFoundError("Retailer was not found.")

    try:
        snapshot = get_retailer_income_snapshot(session, retailer_id)
        threshold = resolve_retailer_settlement_threshold(session)
    except RetailerIncomeError as exc:
        raise RetailerSettlementBatchError(str(exc)) from exc

    if snapshot.recovery_due_ugx > 0:
        return SettlementBatchResult(
            retailer_id=retailer_id,
            settlement_id=None,
            amount_ugx=0,
            threshold_ugx=threshold,
            selected_entry_count=0,
            eligible=False,
            reason="recovery_due",
        )

    if snapshot.available_to_settle_ugx < threshold:
        return SettlementBatchResult(
            retailer_id=retailer_id,
            settlement_id=None,
            amount_ugx=0,
            threshold_ugx=threshold,
            selected_entry_count=0,
            eligible=False,
            reason="below_threshold",
        )

    # If a DRAFT/SUBMITTED settlement already reserves enough value, the
    # snapshot's available amount will be below threshold. The check above
    # therefore also prevents duplicate batch generation.
    entries = session.scalars(_unconsumed_credit_statement(session, retailer_id)).all()

    remaining_capacity = snapshot.available_to_settle_ugx
    selected: list[RetailerPayableEntry] = []
    selected_total = 0

    for entry in entries:
        if entry.amount_ugx > remaining_capacity:
            continue
        selected.append(entry)
        selected_total += entry.amount_ugx
        remaining_capacity -= entry.amount_ugx
        if selected_total >= threshold:
            break

    if selected_total < threshold:
        return SettlementBatchResult(
            retailer_id=retailer_id,
            settlement_id=None,
            amount_ugx=selected_total,
            threshold_ugx=threshold,
            selected_entry_count=len(selected),
            eligible=False,
            reason="whole_entry_boundary_below_threshold",
        )

    reference = f"RET-SET-{uuid4().hex[:20].upper()}"
    idempotency_key = f"retailer-settlement:{uuid4()}"

    settlement = create_draft_settlement(
        session,
        retailer_id=retailer_id,
        amount_ugx=selected_total,
        settlement_reference=reference,
        idempotency_key=idempotency_key,
    )

    for entry in selected:
        attach_payable_entry_to_draft_settlement(
            session,
            settlement_id=settlement.id,
            payable_entry_id=entry.id,
            amount_ugx=entry.amount_ugx,
        )

    return SettlementBatchResult(
        retailer_id=retailer_id,
        settlement_id=settlement.id,
        amount_ugx=selected_total,
        threshold_ugx=threshold,
        selected_entry_count=len(selected),
        eligible=True,
        reason=None,
    )


def generate_retailer_settlement_batch(
    session: Session,
    *,
    retailer_id: UUID | None = None,
    limit: int = 100,
) -> list[SettlementBatchResult]:
    """Generate DRAFT batches for one retailer or all retailers.

    The caller owns the transaction. Successful results should be committed
    together; an individual failure should be handled by the caller's
    transaction boundary so a malformed retailer cannot produce a half-batch.
    """

    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")

    if retailer_id is not None:
        return [generate_retailer_settlement(session, retailer_id=retailer_id)]

    retailer_ids = session.scalars(
        select(Retailer.id)
        .where(Retailer.status == "ACTIVE")
        .order_by(Retailer.id)
        .limit(limit)
    ).all()

    return [
        generate_retailer_settlement(session, retailer_id=retailer_id)
        for retailer_id in retailer_ids
    ]
