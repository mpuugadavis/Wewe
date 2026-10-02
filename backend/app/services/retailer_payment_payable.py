"""Link explicit payment allocations to retailer payable credits.

This module does not calculate retailer earnings, fees, commission, tax, delivery
charges, settlement eligibility, or payout amounts. The allocation amount must
already have been explicitly supplied and persisted by the payment-allocation
service.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RetailerPaymentAllocation, RetailerPayableEntry
from app.services.retailer_payable_ledger import (
    PayableEntryReferenceMismatchError,
    post_payable_entry,
)


class PaymentAllocationPayableLinkError(ValueError):
    """Base error for linking a payment allocation to the payable ledger."""


def post_payable_credit_for_payment_allocation(
    session: Session,
    *,
    allocation_id: UUID,
) -> RetailerPayableEntry:
    """Idempotently post one allocation amount as a retailer payable credit.

    The allocation is the accounting input: no amount is derived from the
    order total, payment total, delivery fee, commission, tax, or other field.
    Replaying the same allocation returns the existing payable entry through
    the ledger's source-reference idempotency guard.
    """
    allocation = session.scalar(
        select(RetailerPaymentAllocation)
        .where(RetailerPaymentAllocation.id == allocation_id)
        .with_for_update()
    )
    if allocation is None:
        raise PaymentAllocationPayableLinkError("allocation_id does not exist")

    if allocation.currency != "UGX":
        raise PaymentAllocationPayableLinkError("payment allocation currency must be UGX")
    if allocation.amount_ugx <= 0:
        raise PaymentAllocationPayableLinkError("payment allocation amount must be greater than zero")

    source_reference = f"payment-allocation:{allocation.id}"

    try:
        return post_payable_entry(
            session,
            retailer_id=allocation.retailer_id,
            order_id=_get_fulfillment_order_id(session, allocation.fulfillment_id),
            fulfillment_id=allocation.fulfillment_id,
            entry_type="CREDIT",
            amount_ugx=allocation.amount_ugx,
            reason="payment_allocation_credit",
            source_reference=source_reference,
            payment_id=allocation.payment_id,
            metadata_json={"payment_allocation_id": str(allocation.id)},
        )
    except PayableEntryReferenceMismatchError as exc:
        raise PaymentAllocationPayableLinkError(str(exc)) from exc


def _get_fulfillment_order_id(session: Session, fulfillment_id: UUID) -> UUID:
    from app.models import RetailerFulfillment

    fulfillment = session.scalar(
        select(RetailerFulfillment)
        .where(RetailerFulfillment.id == fulfillment_id)
    )
    if fulfillment is None:
        raise PaymentAllocationPayableLinkError("allocation fulfillment does not exist")
    return fulfillment.order_id
