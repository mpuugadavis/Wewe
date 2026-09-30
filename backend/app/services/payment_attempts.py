from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Order,
    Payment,
    PaymentReconciliation,
    PaymentRefund,
    utcnow,
)
from app.services.state_transitions import aggregate_payment_status, is_payment_transition_allowed


ReconciliationOutcome = Literal["SUCCESSFUL", "FAILED", "UNRESOLVED"]
RefundOutcome = Literal["CONFIRMED", "FAILED", "UNKNOWN"]


def reserve_refund_attempt(
    db: Session,
    payment_id: UUID,
    amount_ugx: int,
    idempotency_key: str,
    external_reference: str | None = None,
) -> PaymentRefund:
    existing = db.scalar(
        select(PaymentRefund).where(PaymentRefund.idempotency_key == idempotency_key)
    )
    if existing:
        if (
            existing.payment_id == payment_id
            and existing.amount_ugx == amount_ugx
            and existing.external_reference == external_reference
        ):
            return existing
        raise HTTPException(
            status_code=409,
            detail={"code": "refund_idempotency_conflict", "message": "This refund key was already used for a different request."},
        )
    payment_reference = db.get(Payment, payment_id)
    if payment_reference is None:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Payment was not found."})
    order = db.scalar(select(Order).where(Order.id == payment_reference.order_id).with_for_update())
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if order is None or payment is None:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Payment was not found."})
    if payment.status != "SUCCESSFUL" or amount_ugx <= 0:
        raise HTTPException(
            status_code=409,
            detail={"code": "payment_not_refundable", "message": "Only captured funds can be reserved for refund."},
        )
    reserved = db.scalar(
        select(func.coalesce(func.sum(PaymentRefund.amount_ugx), 0)).where(
            PaymentRefund.payment_id == payment.id,
            PaymentRefund.status.in_(["SUBMITTED", "UNKNOWN", "CONFIRMED"]),
        )
    ) or 0
    if reserved + amount_ugx > payment.amount_ugx:
        raise HTTPException(
            status_code=409,
            detail={"code": "refund_balance_exceeded", "message": "Refund amount exceeds the remaining captured balance."},
        )
    refund = PaymentRefund(
        payment_id=payment.id,
        amount_ugx=amount_ugx,
        idempotency_key=idempotency_key,
        external_reference=external_reference,
        status="SUBMITTED",
    )
    db.add(refund)
    db.flush()
    return refund


def resolve_refund_attempt(
    db: Session,
    refund_id: UUID,
    outcome: RefundOutcome,
    evidence: dict | None = None,
) -> PaymentRefund:
    refund_reference = db.get(PaymentRefund, refund_id)
    if refund_reference is None:
        raise HTTPException(status_code=404, detail={"code": "refund_not_found", "message": "Refund attempt was not found."})
    payment_reference = db.get(Payment, refund_reference.payment_id)
    order = db.scalar(
        select(Order).where(Order.id == payment_reference.order_id).with_for_update()
    ) if payment_reference else None
    payment = db.scalar(
        select(Payment).where(Payment.id == refund_reference.payment_id).with_for_update()
    ) if payment_reference else None
    refund = db.scalar(select(PaymentRefund).where(PaymentRefund.id == refund_id).with_for_update())
    if payment is None or order is None or refund is None:
        raise HTTPException(status_code=404, detail={"code": "refund_not_found", "message": "Refund attempt was not found."})
    if refund.status == outcome:
        return refund
    if refund.status not in {"SUBMITTED", "UNKNOWN"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "refund_already_resolved", "message": "Refund attempt has already been resolved."},
        )
    refund.status = outcome
    refund.evidence = evidence
    if outcome in {"CONFIRMED", "FAILED"}:
        refund.resolved_at = utcnow()
    db.flush()
    if outcome == "CONFIRMED":
        confirmed = db.scalar(
            select(func.coalesce(func.sum(PaymentRefund.amount_ugx), 0)).where(
                PaymentRefund.payment_id == payment.id,
                PaymentRefund.status == "CONFIRMED",
            )
        ) or 0
        if confirmed == payment.amount_ugx:
            if not is_payment_transition_allowed(payment.status, "REFUNDED"):
                raise HTTPException(
                    status_code=409,
                    detail={"code": "payment_not_refundable", "message": "Payment cannot be marked refunded in its current state."},
                )
            payment.status = "REFUNDED"
            payment.resolved_at = utcnow()
    db.flush()
    order.payment_status = aggregate_payment_status(
        db.scalars(select(Payment.status).where(Payment.order_id == order.id)).all()
    )
    return refund


def request_reconciliation(db: Session, payment_id: UUID, reason: str) -> PaymentReconciliation:
    payment_reference = db.get(Payment, payment_id)
    if payment_reference is None:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Payment was not found."})
    order = db.scalar(select(Order).where(Order.id == payment_reference.order_id).with_for_update())
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if order is None or payment is None:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Payment was not found."})
    if payment.status not in {"PENDING", "UNKNOWN"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "payment_not_reconcilable", "message": "Only unresolved payment attempts can be reconciled."},
        )
    entry = PaymentReconciliation(
        payment_id=payment.id,
        state="REQUESTED",
        source="SYSTEM",
        evidence={"reason": reason},
    )
    db.add(entry)
    db.flush()
    return entry


def record_reconciliation_attempt(
    db: Session,
    payment_id: UUID,
    evidence: dict | None = None,
) -> PaymentReconciliation:
    payment = _lock_unresolved_payment(db, payment_id)
    entry = PaymentReconciliation(
        payment_id=payment.id,
        state="ATTEMPTED",
        source="SYSTEM",
        evidence=evidence,
        attempted_at=utcnow(),
    )
    db.add(entry)
    db.flush()
    return entry


def record_reconciliation_unresolved(
    db: Session,
    payment_id: UUID,
    evidence: dict | None = None,
) -> PaymentReconciliation:
    payment = _lock_unresolved_payment(db, payment_id)
    entry = PaymentReconciliation(
        payment_id=payment.id,
        state="UNRESOLVED",
        source="SYSTEM",
        evidence=evidence,
    )
    db.add(entry)
    db.flush()
    return entry


def resolve_payment_reconciliation(
    db: Session,
    payment_id: UUID,
    outcome: ReconciliationOutcome,
    evidence: dict,
    authoritative: bool,
    provider_reference: str | None = None,
) -> PaymentReconciliation:
    payment_reference = db.get(Payment, payment_id)
    if payment_reference is None:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Payment was not found."})
    order = db.scalar(select(Order).where(Order.id == payment_reference.order_id).with_for_update())
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if order is None or payment is None:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Payment was not found."})
    if outcome != "UNRESOLVED" and not authoritative:
        raise HTTPException(
            status_code=409,
            detail={"code": "reconciliation_not_authoritative", "message": "Only authoritative provider evidence can resolve an uncertain payment."},
        )
    if outcome == "UNRESOLVED":
        if payment.status not in {"PENDING", "UNKNOWN"}:
            return _record_payment_conflict(db, payment.id, evidence, outcome)
        record = PaymentReconciliation(
            payment_id=payment.id,
            state="UNRESOLVED",
            source="PROVIDER",
            evidence=evidence,
        )
        db.add(record)
        db.flush()
        return record
    if payment.status not in {"PENDING", "UNKNOWN"}:
        return _record_payment_conflict(db, payment.id, evidence, outcome)
    if not is_payment_transition_allowed(payment.status, outcome):
        return _record_payment_conflict(db, payment.id, evidence, outcome)
    if provider_reference:
        matching_payment = db.scalar(
            select(Payment.id).where(
                Payment.provider_reference == provider_reference,
                Payment.id != payment.id,
            )
        )
        if matching_payment:
            return _record_payment_conflict(
                db,
                payment.id,
                {**evidence, "provider_reference_conflict": True},
                outcome,
            )
    payment.status = outcome
    payment.resolved_at = utcnow()
    if outcome == "SUCCESSFUL":
        payment.paid_at = payment.resolved_at
    if provider_reference and provider_reference != payment.attempt_reference:
        payment.provider_reference = provider_reference
    db.flush()
    order.payment_status = aggregate_payment_status(
        db.scalars(select(Payment.status).where(Payment.order_id == order.id)).all()
    )
    record = PaymentReconciliation(
        payment_id=payment.id,
        state="AUTHORITATIVE_SUCCESS" if outcome == "SUCCESSFUL" else "AUTHORITATIVE_FAILURE",
        source="PROVIDER",
        evidence=evidence,
        resolved_at=utcnow(),
    )
    db.add(record)
    db.flush()
    if outcome == "SUCCESSFUL" and order.status == "CANCELLED":
        db.add(
            PaymentReconciliation(
                payment_id=payment.id,
                state="MANUAL_REVIEW",
                source="SYSTEM",
                evidence={"reason": "successful_capture_after_order_cancellation"},
            )
        )
        db.flush()
    return record


def record_payment_conflict(
    db: Session,
    payment_id: UUID,
    payment_event_id: UUID,
    evidence: dict,
) -> PaymentReconciliation:
    entry = PaymentReconciliation(
        payment_id=payment_id,
        payment_event_id=payment_event_id,
        state="CONFLICT",
        source="PROVIDER",
        evidence=evidence,
    )
    db.add(entry)
    db.flush()
    return entry


def record_cancelled_order_capture_review(
    db: Session,
    payment_id: UUID,
    payment_event_id: UUID,
) -> PaymentReconciliation:
    entry = PaymentReconciliation(
        payment_id=payment_id,
        payment_event_id=payment_event_id,
        state="MANUAL_REVIEW",
        source="SYSTEM",
        evidence={"reason": "successful_capture_after_order_cancellation"},
    )
    db.add(entry)
    db.flush()
    return entry


def _lock_unresolved_payment(db: Session, payment_id: UUID) -> Payment:
    reference = db.get(Payment, payment_id)
    if reference is None:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Payment was not found."})
    order = db.scalar(select(Order).where(Order.id == reference.order_id).with_for_update())
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if order is None or payment is None:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Payment was not found."})
    if payment.status not in {"PENDING", "UNKNOWN"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "payment_not_reconcilable", "message": "Only unresolved payment attempts can be reconciled."},
        )
    return payment


def _record_payment_conflict(
    db: Session,
    payment_id: UUID,
    evidence: dict,
    outcome: str,
) -> PaymentReconciliation:
    entry = PaymentReconciliation(
        payment_id=payment_id,
        state="CONFLICT",
        source="PROVIDER",
        evidence={"reported_outcome": outcome, **evidence},
    )
    db.add(entry)
    db.flush()
    return entry
