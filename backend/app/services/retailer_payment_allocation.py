"""Auditable allocation of successful online payments to retailer fulfillments.

The allocation amount is an explicit accounting input. This module does not
derive retailer earnings, commission, fees, tax, or settlement eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Order, OrderItem, Payment, RetailerFulfillment, RetailerPaymentAllocation


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


def allocate_successful_payment_for_order(
    session: Session,
    *,
    payment_id: UUID,
) -> list[RetailerPaymentAllocation]:
    """Allocate merchandise value net of the order's snapshotted commission.

    Delivery fees remain platform-held cash used to fund rider earnings. The
    retailer allocations therefore cover only merchandise payable to retailers.
    """
    payment = session.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if payment is None:
        raise RetailerPaymentAllocationError("payment_id does not exist")
    if payment.status != "SUCCESSFUL":
        raise RetailerPaymentAllocationError("only SUCCESSFUL payments can be allocated")

    order_obj = session.scalar(select(Order).where(Order.id == payment.order_id).with_for_update())
    if order_obj is None:
        raise RetailerPaymentAllocationError("payment order does not exist")
    if order_obj.platform_commission_ugx < 0 or order_obj.platform_commission_ugx > order_obj.subtotal_ugx:
        raise RetailerPaymentAllocationError("order commission snapshot is invalid")

    fulfillments = session.scalars(
        select(RetailerFulfillment)
        .where(RetailerFulfillment.order_id == order_obj.id)
        .order_by(RetailerFulfillment.id)
        .with_for_update()
    ).all()
    if not fulfillments:
        raise RetailerPaymentAllocationError("payment order has no retailer fulfillments")

    allocations: list[RetailerPaymentAllocation] = []
    allocated_total = 0
    for fulfillment in fulfillments:
        merchandise = session.scalar(
            select(func.coalesce(func.sum(OrderItem.line_total_ugx), 0)).where(
                OrderItem.order_id == order_obj.id,
                OrderItem.retailer_id == fulfillment.retailer_id,
            )
        )
        merchandise_ugx = int(merchandise or 0)
        if merchandise_ugx <= 0:
            continue
        commission = int(
            (Decimal(merchandise_ugx) * order_obj.platform_commission_percent / Decimal("100"))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        payable = merchandise_ugx - commission
        if payable <= 0:
            continue
        allocation = allocate_successful_payment_to_fulfillment(
            session,
            payment_id=payment_id,
            fulfillment_id=fulfillment.id,
            amount_ugx=payable,
        )
        allocations.append(allocation)
        allocated_total += payable

    expected = order_obj.subtotal_ugx - order_obj.platform_commission_ugx
    if allocated_total != expected:
        raise RetailerPaymentAllocationError(
            f"retailer allocations total {allocated_total} UGX but expected {expected} UGX"
        )
    if allocated_total + order_obj.delivery_fee_ugx > payment.amount_ugx:
        raise RetailerPaymentAllocationError("retailer allocations exceed the captured order funds")
    return allocations
