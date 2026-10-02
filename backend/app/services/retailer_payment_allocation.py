"""Auditable allocation of successful online payments to retailer fulfillments.

The allocation amount is an explicit accounting input. This module does not
derive retailer earnings, commission, fees, tax, or settlement eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Payment, RetailerFulfillment, RetailerPaymentAllocation


class RetailerPaymentAllocationError(ValueError):
    """Base error for invalid payment-allocation operations."""


class PaymentAllocationConflictError(RetailerPaymentAllocationError):
    """An existing allocation conflicts with the requested allocation."""


@dataclass(frozen=True, slots=True)
class PaymentAllocationTotals:
    payment_id: UUID
    payment_amount_ugx: int
    allocated_ugx: int

    @property
    def remaining_ugx(self) -> int:
        return self.payment_amount_ugx - self.allocated_ugx


def get_payment_allocation_totals(
    session: Session,
    payment_id: UUID,
) -> PaymentAllocationTotals:
    payment = session.scalar(select(Payment).where(Payment.id == payment_id))
    if payment is None:
        raise RetailerPaymentAllocationError("payment_id does not exist")

    allocated = session.scalar(
        select(func.coalesce(func.sum(RetailerPaymentAllocation.amount_ugx), 0)).where(
            RetailerPaymentAllocation.payment_id == payment_id
        )
    )

    return PaymentAllocationTotals(
        payment_id=payment.id,
        payment_amount_ugx=payment.amount_ugx,
        allocated_ugx=int(allocated or 0),
    )


def allocate_successful_payment_to_fulfillment(
    session: Session,
    *,
    payment_id: UUID,
    fulfillment_id: UUID,
    amount_ugx: int,
) -> RetailerPaymentAllocation:
    """Create an idempotent allocation from a successful payment.

    The caller supplies the explicit allocation amount. The function only
    validates that the payment is successful, the fulfillment belongs to the
    payment's order, and the payment cannot be allocated above its captured
    amount.
    """

    if amount_ugx <= 0:
        raise RetailerPaymentAllocationError("amount_ugx must be greater than zero")

    payment = session.scalar(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    )
    if payment is None:
        raise RetailerPaymentAllocationError("payment_id does not exist")
    if payment.status != "SUCCESSFUL":
        raise RetailerPaymentAllocationError(
            "only SUCCESSFUL online payments can be allocated"
        )
    if payment.currency != "UGX":
        raise RetailerPaymentAllocationError("payment currency must be UGX")

    fulfillment = session.scalar(
        select(RetailerFulfillment)
        .where(RetailerFulfillment.id == fulfillment_id)
        .with_for_update()
    )
    if fulfillment is None:
        raise RetailerPaymentAllocationError("fulfillment_id does not exist")
    if fulfillment.order_id != payment.order_id:
        raise PaymentAllocationConflictError(
            "fulfillment does not belong to the payment order"
        )

    existing = session.scalar(
        select(RetailerPaymentAllocation).where(
            RetailerPaymentAllocation.payment_id == payment_id,
            RetailerPaymentAllocation.fulfillment_id == fulfillment_id,
        )
    )
    if existing is not None:
        if existing.amount_ugx != amount_ugx or existing.retailer_id != fulfillment.retailer_id:
            raise PaymentAllocationConflictError(
                "payment/fulfillment allocation already exists with different data"
            )
        return existing

    allocated = session.scalar(
        select(func.coalesce(func.sum(RetailerPaymentAllocation.amount_ugx), 0))
        .where(RetailerPaymentAllocation.payment_id == payment_id)
    )
    allocated_ugx = int(allocated or 0)

    if allocated_ugx + amount_ugx > payment.amount_ugx:
        raise PaymentAllocationConflictError(
            "payment allocations cannot exceed the successful payment amount"
        )

    allocation = RetailerPaymentAllocation(
        id=uuid4(),
        payment_id=payment.id,
        fulfillment_id=fulfillment.id,
        retailer_id=fulfillment.retailer_id,
        amount_ugx=amount_ugx,
        currency="UGX",
    )
    session.add(allocation)
    session.flush()
    return allocation
