from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.limiter import limiter
from app.dependencies import Principal, require_roles
from app.models import (
    NotificationOutbox,
    Order,
    Payment,
    PaymentEvent,
    PaymentReconciliation,
    PaymentRefund,
    utcnow,
)
from app.schemas import PaymentWebhookIn
from app.services.payment_attempts import (
    record_cancelled_order_capture_review,
    record_payment_conflict,
    reserve_refund_attempt,
    resolve_refund_attempt,
)
from app.services.payments import PaymentProviderUnavailable, payment_providers
from app.services.state_transitions import aggregate_payment_status, is_payment_transition_allowed

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/flutterwave/webhook")
@limiter.limit("120/minute")
async def flutterwave_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Verify Flutterwave's signature and authoritative transaction before applying an event."""
    raw_body = await request.body()
    signature = request.headers.get("verif-hash", "")
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail={"code": "invalid_webhook", "message": "Webhook body must be valid JSON."}) from None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise HTTPException(status_code=400, detail={"code": "invalid_webhook", "message": "Flutterwave webhook payload is invalid."})
    try:
        adapter = payment_providers.get("FLUTTERWAVE")
    except PaymentProviderUnavailable:
        raise HTTPException(status_code=503, detail={"code": "payment_provider_unavailable", "message": "Flutterwave is not configured."}) from None
    if not adapter.verify_webhook(raw_body, signature):
        raise HTTPException(status_code=401, detail={"code": "invalid_signature", "message": "Flutterwave webhook signature is invalid."})
    data = payload["data"]
    transaction_id = str(data.get("id", ""))
    if payload.get("event") != "charge.completed" or not transaction_id.isdigit():
        return {"received": True, "ignored": True}
    try:
        verified = adapter.verify_transaction(transaction_id)
    except (ValueError, RuntimeError):
        raise HTTPException(status_code=502, detail={"code": "transaction_verification_unavailable", "message": "Flutterwave transaction verification could not be completed."}) from None
    tx_ref = verified.get("tx_ref")
    currency = str(verified.get("currency", "")).upper()
    try:
        amount = Decimal(str(verified.get("amount")))
    except (InvalidOperation, TypeError):
        raise HTTPException(status_code=422, detail={"code": "invalid_verified_amount", "message": "Flutterwave returned an invalid transaction amount."}) from None
    if str(verified.get("id", "")) != transaction_id or not tx_ref or str(data.get("tx_ref", "")) != str(tx_ref) or currency != "UGX" or not amount.is_finite() or amount != amount.to_integral_value() or amount <= 0:
        raise HTTPException(status_code=422, detail={"code": "transaction_details_mismatch", "message": "Flutterwave transaction details did not match the webhook."})
    outcome = str(verified.get("status", "")).lower()
    if outcome not in {"successful", "failed"}:
        return {"received": True, "status": "pending"}
    normalized = PaymentWebhookIn(
        provider_reference=str(tx_ref),
        provider_event_id=transaction_id,
        amount_ugx=int(amount),
        currency="UGX",
        status="SUCCESSFUL" if outcome == "successful" else "FAILED",
    )
    return await provider_webhook("FLUTTERWAVE", normalized, request, signature=signature, db=db)



@router.post("/webhooks/{provider}")
@limiter.limit("120/minute")
async def provider_webhook(
    provider: str,
    payload: PaymentWebhookIn,
    request: Request,
    signature: str | None = Header(default=None, alias="X-Webhook-Signature"),
    db: Session = Depends(get_db),
) -> dict:
    if not signature:
        raise HTTPException(status_code=503, detail={"code": "webhook_unconfigured", "message": "Payment callbacks are not configured."})
    provider_name = provider.upper().replace("-", "_")
    try:
        adapter = payment_providers.get(provider_name)
    except PaymentProviderUnavailable:
        raise HTTPException(status_code=503, detail={"code": "payment_provider_unavailable", "message": "This payment provider is not configured."}) from None
    if not adapter.verify_webhook(await request.body(), signature):
        raise HTTPException(status_code=401, detail={"code": "invalid_signature", "message": "Payment callback signature is invalid."})
    event_id = f"{provider_name}:{payload.provider_event_id}"
    prior_event = db.scalar(
        select(PaymentEvent).where(PaymentEvent.provider_event_id == event_id)
    )
    if prior_event:
        prior_payment_reference = db.get(Payment, prior_event.payment_id)
        if prior_payment_reference:
            db.scalar(
                select(Order).where(Order.id == prior_payment_reference.order_id).with_for_update()
            )
        prior_payment = db.scalar(
            select(Payment).where(Payment.id == prior_event.payment_id).with_for_update()
        )
        if (
            prior_payment is not None
            and prior_event.status == payload.status
            and prior_payment.provider == provider_name
            and prior_payment.amount_ugx == payload.amount_ugx
            and prior_payment.currency == payload.currency
            and payload.provider_reference
            in {prior_payment.provider_reference, prior_payment.attempt_reference}
        ):
            return {"received": True, "duplicate": True}
        if prior_payment:
            record_payment_conflict(
                db,
                prior_payment.id,
                prior_event.id,
                {
                    "provider_event_id": event_id,
                    "previous_event_status": prior_event.status,
                    "conflicting_event_status": payload.status,
                    "conflicting_amount_ugx": payload.amount_ugx,
                    "conflicting_reference": payload.provider_reference,
                },
            )
            db.commit()
        raise HTTPException(
            status_code=409,
            detail={"code": "payment_event_conflict", "message": "The provider reused an event ID with a different outcome; the conflict was recorded for review."},
        )
    payment_reference = db.scalar(
        select(Payment).where(
            or_(
                Payment.provider_reference == payload.provider_reference,
                Payment.attempt_reference == payload.provider_reference,
            )
        )
    )
    if payment_reference is None or payment_reference.provider != provider_name:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Payment reference was not found."})
    order = db.scalar(select(Order).where(Order.id == payment_reference.order_id).with_for_update())
    payment = db.scalar(select(Payment).where(Payment.id == payment_reference.id).with_for_update())
    if payment is None or payment.provider != provider_name:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Payment reference was not found."})
    prior_event = db.scalar(
        select(PaymentEvent).where(PaymentEvent.provider_event_id == event_id)
    )
    if prior_event:
        if prior_event.payment_id == payment.id and prior_event.status == payload.status:
            return {"received": True, "duplicate": True}
        if prior_event.payment_id == payment.id:
            record_payment_conflict(
                db,
                payment.id,
                prior_event.id,
                {
                    "provider_event_id": event_id,
                    "previous_event_status": prior_event.status,
                    "conflicting_event_status": payload.status,
                },
            )
            db.commit()
        raise HTTPException(
            status_code=409,
            detail={"code": "payment_event_conflict", "message": "The provider event conflicts with a previously recorded outcome."},
        )
    if payment.amount_ugx != payload.amount_ugx or payment.currency != payload.currency:
        raise HTTPException(status_code=422, detail={"code": "payment_amount_mismatch", "message": "Payment amount or currency does not match the order."})
    evidence = {
        "provider": provider_name,
        "provider_reference": payload.provider_reference,
        "provider_event_id": event_id,
        "amount_ugx": payload.amount_ugx,
        "currency": payload.currency,
        "outcome": payload.status,
    }
    was_unknown = payment.status == "UNKNOWN"
    payment_event = PaymentEvent(
        payment_id=payment.id,
        provider_event_id=event_id,
        status=payload.status,
    )
    db.add(payment_event)
    db.flush()
    if payment.status == payload.status:
        payment_event.disposition = "IDEMPOTENT"
        db.commit()
        return {"received": True, "duplicate": True}
    if payload.status == "REFUNDED":
        if payment.status != "SUCCESSFUL":
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail={"code": "payment_not_refundable", "message": "Only a successful captured payment can be refunded."},
            )
        try:
            refund = reserve_refund_attempt(
                db,
                payment.id,
                amount_ugx=payment.amount_ugx,
                idempotency_key=f"provider-event:{event_id}",
                external_reference=event_id,
            )
            resolve_refund_attempt(
                db,
                refund.id,
                outcome="CONFIRMED",
                evidence=evidence,
            )
        except HTTPException:
            payment_event.disposition = "CONFLICT"
            db.flush()
            record_payment_conflict(db, payment.id, payment_event.id, evidence)
            db.commit()
            raise HTTPException(
                status_code=409,
                detail={"code": "payment_refund_conflict", "message": "The refund event exceeds or conflicts with the captured balance and was held for review."},
            ) from None
    elif is_payment_transition_allowed(payment.status, payload.status):
        payment.status = payload.status
        payment.resolved_at = utcnow()
        if payload.status == "SUCCESSFUL":
            payment.paid_at = payment.resolved_at
        if payload.provider_reference != payment.attempt_reference:
            payment.provider_reference = payload.provider_reference
    else:
        payment_event.disposition = "CONFLICT"
        db.flush()
        record_payment_conflict(db, payment.id, payment_event.id, evidence)
        db.commit()
        raise HTTPException(
            status_code=409,
            detail={"code": "payment_outcome_conflict", "message": "The provider outcome conflicts with the current payment state and was recorded for review."},
        )
    if order:
        db.flush()
        order.payment_status = aggregate_payment_status(
            db.scalars(select(Payment.status).where(Payment.order_id == order.id)).all()
        )
        if payment_event.disposition == "APPLIED":
            db.add(
                NotificationOutbox(
                    user_id=payment.customer_id,
                    event_type=f"PAYMENT_{payload.status}",
                    payload={"order_id": str(order.id), "order_number": order.order_number},
                )
            )
        if payment.status == "SUCCESSFUL" and order.status == "CANCELLED":
            record_cancelled_order_capture_review(db, payment.id, payment_event.id)
    if was_unknown and payment.status in {"SUCCESSFUL", "FAILED"}:
        db.add(
            PaymentReconciliation(
                payment_id=payment.id,
                payment_event_id=payment_event.id,
                state="AUTHORITATIVE_SUCCESS" if payment.status == "SUCCESSFUL" else "AUTHORITATIVE_FAILURE",
                source="PROVIDER",
                evidence=evidence,
                resolved_at=utcnow(),
            )
        )
    db.commit()
    return {"received": True, "status": payment.status}


@router.get("/{payment_id}")
def get_payment(
    payment_id: UUID,
    principal: Principal = Depends(require_roles("CUSTOMER", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    payment = db.get(Payment, payment_id)
    if payment is None or (principal.user.role == "CUSTOMER" and payment.customer_id != principal.user.id):
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Payment was not found."})
    return {
        "id": payment.id,
        "order_id": payment.order_id,
        "amount_ugx": payment.amount_ugx,
        "currency": payment.currency,
        "method": payment.method,
        "provider": payment.provider,
        "provider_reference": payment.provider_reference,
        "status": payment.status,
        "attempt_reference": payment.attempt_reference,
        "created_at": payment.created_at,
        "initiated_at": payment.initiated_at,
        "paid_at": payment.paid_at,
        "resolved_at": payment.resolved_at,
        "refunds": [
            {
                "id": refund.id,
                "amount_ugx": refund.amount_ugx,
                "status": refund.status,
                "external_reference": refund.external_reference,
                "created_at": refund.created_at,
                "resolved_at": refund.resolved_at,
            }
            for refund in db.scalars(
                select(PaymentRefund)
                .where(PaymentRefund.payment_id == payment.id)
                .order_by(PaymentRefund.created_at.desc())
            ).all()
        ],
    }
