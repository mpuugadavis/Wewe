"""Technical operations for the retailer payable ledger.

This module intentionally contains accounting primitives only. It does not
decide which order components are payable to a retailer, settlement cadence,
thresholds, fees, taxes, payout rails, or eligibility. Those remain gated by
the unresolved COM-SET-001 business parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Order, RetailerFulfillment, RetailerPayableEntry


class RetailerPayableLedgerError(ValueError):
    """Base error for invalid retailer payable ledger operations."""


class PayableEntrySourceConflictError(RetailerPayableLedgerError):
    """The idempotency source reference already exists with different data."""


class PayableEntryReferenceMismatchError(RetailerPayableLedgerError):
    """The supplied order, fulfillment, retailer, or payment references disagree."""


@dataclass(frozen=True, slots=True)
class PayableLedgerBalance:
    retailer_id: UUID
    credit_ugx: int
    debit_ugx: int

    @property
    def balance_ugx(self) -> int:
        return self.credit_ugx - self.debit_ugx


def get_retailer_payable_balance(
    session: Session,
    retailer_id: UUID,
    *,
    lock: bool = False,
) -> PayableLedgerBalance:
    """Return the signed ledger balance without applying settlement policy.

    A positive balance means posted credits exceed posted debits. This is a
    ledger fact, not a statement that the amount is eligible for settlement.
    """

    stmt = (
        select(
            RetailerPayableEntry.entry_type,
            func.coalesce(func.sum(RetailerPayableEntry.amount_ugx), 0),
        )
        .where(RetailerPayableEntry.retailer_id == retailer_id)
        .group_by(RetailerPayableEntry.entry_type)
    )
    if lock:
        stmt = stmt.with_for_update()

    totals = dict(session.execute(stmt).all())
    credit = int(totals.get("CREDIT", 0))
    debit = int(totals.get("DEBIT", 0))
    return PayableLedgerBalance(retailer_id=retailer_id, credit_ugx=credit, debit_ugx=debit)


def post_payable_entry(
    session: Session,
    *,
    retailer_id: UUID,
    order_id: UUID,
    fulfillment_id: UUID,
    entry_type: str,
    amount_ugx: int,
    reason: str,
    source_reference: str,
    payment_id: UUID | None = None,
    metadata_json: dict | None = None,
) -> RetailerPayableEntry:
    """Post an idempotent payable ledger entry.

    The caller supplies the business-approved amount and reason. This function
    only enforces ledger invariants and reference consistency; it never derives
    a retailer payable amount from an order or payment.
    """

    if entry_type not in {"CREDIT", "DEBIT"}:
        raise RetailerPayableLedgerError("entry_type must be CREDIT or DEBIT")
    if amount_ugx <= 0:
        raise RetailerPayableLedgerError("amount_ugx must be greater than zero")
    if not source_reference.strip():
        raise RetailerPayableLedgerError("source_reference is required for idempotent posting")
    if not reason.strip():
        raise RetailerPayableLedgerError("reason is required")

    existing = session.scalar(
        select(RetailerPayableEntry).where(
            RetailerPayableEntry.source_reference == source_reference
        )
    )
    if existing is not None:
        if (
            existing.retailer_id != retailer_id
            or existing.order_id != order_id
            or existing.fulfillment_id != fulfillment_id
            or existing.payment_id != payment_id
            or existing.entry_type != entry_type
            or existing.amount_ugx != amount_ugx
            or existing.reason != reason
        ):
            raise PayableEntrySourceConflictError(
                f"source_reference {source_reference!r} already exists with different data"
            )
        return existing

    fulfillment = session.scalar(
        select(RetailerFulfillment).where(RetailerFulfillment.id == fulfillment_id)
    )
    if fulfillment is None:
        raise PayableEntryReferenceMismatchError("fulfillment_id does not exist")
    if fulfillment.retailer_id != retailer_id or fulfillment.order_id != order_id:
        raise PayableEntryReferenceMismatchError(
            "retailer_id/order_id do not match the fulfillment"
        )

    order = session.scalar(select(Order).where(Order.id == order_id))
    if order is None:
        raise PayableEntryReferenceMismatchError("order_id does not exist")

    if payment_id is not None:
        from app.models import Payment

        payment = session.scalar(select(Payment).where(Payment.id == payment_id))
        if payment is None:
            raise PayableEntryReferenceMismatchError("payment_id does not exist")
        if payment.order_id != order_id:
            raise PayableEntryReferenceMismatchError(
                "payment_id does not belong to the supplied order"
            )

    entry = RetailerPayableEntry(
        id=uuid4(),
        retailer_id=retailer_id,
        order_id=order_id,
        fulfillment_id=fulfillment_id,
        payment_id=payment_id,
        entry_type=entry_type,
        amount_ugx=amount_ugx,
        currency="UGX",
        reason=reason,
        source_reference=source_reference,
        metadata_json=metadata_json,
    )
    session.add(entry)
    session.flush()
    return entry
