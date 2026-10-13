import json
from decimal import Decimal, InvalidOperation
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
    DeliveryPayoutBatch,
    utcnow,
)
from app.schemas import PaymentWebhookIn
from app.services.retailer_payment_allocation import allocate_successful_payment_for_order
from app.services.retailer_payment_payable import post_payable_credit_for_payment_allocation
from app.services.rider_payout_batches import (
    fail_rider_payout_batch,
    settle_rider_payout_batch,
    RiderPayoutBatchError,
)
from app.services.payment_attempts import (
    record_cancelled_order_capture_review,
    record_payment_conflict,
    reserve_refund_attempt,
    resolve_refund_attempt,
)
from app.services.payments import PaymentProviderUnavailable, payment_providers
from app.services.state_transitions import aggregate_payment_status, is_payment_transition_allowed

router = APIRouter(prefix="/payments", tags=["payments"])


def _pawapay_operation_payload(payload: object, identifier: str) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_callback", "message": "PawaPay callback payload is invalid."},
        )
    value = payload.get(identifier)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_callback", "message": f"PawaPay callback is missing {identifier}."},
        )
    return payload


@router.post("/pawapay/checkout-callback")
@limiter.limit("120/minute")
async def pawapay_checkout_callback(request: Request) -> dict:
    """Acknowledge PawaPay checkout lifecycle events.

    A checkout is not itself proof of a captured deposit. The deposit callback
    remains authoritative for WEWE order-payment state.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_callback", "message": "PawaPay callback body must be valid JSON."},
        ) from None
    payload = _pawapay_operation_payload(payload, "checkoutId")
    return {
        "received": True,
        "operation": "CHECKOUT",
        "checkout_id": payload["checkoutId"],
        "status": payload.get("status"),
    }



@router.post("/pawapay/deposit-callback")
@limiter.limit("120/minute")
async def pawapay_deposit_callback(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Receive the final asynchronous PawaPay deposit outcome."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_callback", "message": "PawaPay callback body must be valid JSON."},
        ) from None

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_callback", "message": "PawaPay callback payload is invalid."},
        )

    deposit_id = payload.get("depositId")
    status = str(payload.get("status", "")).upper()
    if not isinstance(deposit_id, str) or not deposit_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_callback", "message": "PawaPay callback is missing depositId."},
        )
    if status not in {"COMPLETED", "FAILED"}:
        return {"received": True, "ignored": True, "status": status}

    return _reconcile_pawapay_deposit(deposit_id, db)


def _reconcile_pawapay_deposit(deposit_id: str, db: Session) -> dict:
    # Callback payloads are notifications, not the authoritative payment
    # record. Ask PawaPay for the deposit status so WEWE does not depend on
    # callback field names such as depositedAmount/currency varying by API
    # representation.
    try:
        pawapay = payment_providers.get("PAWAPAY")
        status_payload = pawapay.get_deposit_status(deposit_id)  # type: ignore[attr-defined]
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "provider_status_unavailable",
                "message": "PawaPay callback was received, but its authoritative deposit status could not be retrieved.",
                "error_type": type(exc).__name__,
            },
        ) from None

    authoritative_status = str(status_payload.get("status", "")).upper()
    if authoritative_status not in {"COMPLETED", "FAILED"}:
        return {"received": True, "ignored": True, "status": authoritative_status or "UNKNOWN"}

    currency = str(status_payload.get("currency", "")).upper()
    raw_amount = (
        status_payload.get("amount")
        or status_payload.get("depositedAmount")
        or status_payload.get("requestedAmount")
    )
    try:
        amount = Decimal(str(raw_amount))
    except (InvalidOperation, TypeError):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_callback_amount", "message": "PawaPay returned an invalid deposit amount."},
        ) from None

    if currency != "UGX" or not amount.is_finite() or amount != amount.to_integral_value() or amount <= 0:
        raise HTTPException(
            status_code=422,
            detail={"code": "callback_details_mismatch", "message": "PawaPay deposit amount or currency is invalid."},
        )

    normalized = PaymentWebhookIn(
        provider_reference=deposit_id,
        provider_event_id=deposit_id,
        amount_ugx=int(amount),
        currency="UGX",
        status="SUCCESSFUL" if authoritative_status == "COMPLETED" else "FAILED",
    )
    return _apply_payment_event("PAWAPAY", normalized, db)


@router.post("/pawapay/payout-callback")
@limiter.limit("120/minute")
async def pawapay_payout_callback(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Apply final PawaPay payout outcomes to a submitted rider batch when linked."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_callback", "message": "PawaPay callback body must be valid JSON."},
        ) from None

    payload = _pawapay_operation_payload(payload, "payoutId")
    payout_id = payload["payoutId"]
    status = str(payload.get("status", "")).upper()

    if status not in {"COMPLETED", "FAILED"}:
        return {
            "received": True,
            "operation": "PAYOUT",
            "payout_id": payout_id,
            "ignored": True,
            "status": status,
        }

    batch = db.scalar(
        select(DeliveryPayoutBatch)
        .where(DeliveryPayoutBatch.payout_reference == payout_id)
        .with_for_update()
    )
    if batch is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "payout_not_found",
                "message": "No local rider payout batch matches this PawaPay payoutId.",
            },
        )

    try:
        if status == "COMPLETED":
            settle_rider_payout_batch(
                db,
                batch_id=batch.id,
                payout_reference=payout_id,
            )
        else:
            fail_rider_payout_batch(db, batch_id=batch.id)
        db.commit()
    except RiderPayoutBatchError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "payout_lifecycle_conflict",
                "message": str(exc),
            },
        ) from exc

    return {
        "received": True,
        "operation": "PAYOUT",
        "payout_id": payout_id,
        "status": "SETTLED" if status == "COMPLETED" else "FAILED",
    }


@router.post("/pawapay/refund-callback")
@limiter.limit("120/minute")
async def pawapay_refund_callback(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Apply final PawaPay refund outcomes to a local PaymentRefund."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_callback", "message": "PawaPay callback body must be valid JSON."},
        ) from None
    payload = _pawapay_operation_payload(payload, "refundId")
    refund_id = payload["refundId"]
    status = str(payload.get("status", "")).upper()

    if status not in {"COMPLETED", "FAILED"}:
        return {
            "received": True,
            "operation": "REFUND",
            "refund_id": refund_id,
            "ignored": True,
            "status": status,
        }

    refund = db.scalar(
        select(PaymentRefund).where(
            PaymentRefund.external_reference == refund_id
        )
    )
    if refund is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "refund_not_found",
                "message": "No local refund attempt matches this PawaPay refundId.",
            },
        )

    evidence = {
        "provider": "PAWAPAY",
        "refund_id": refund_id,
        "status": status,
        "payload": payload,
    }
    try:
        resolve_refund_attempt(
            db,
            refund.id,
            outcome="CONFIRMED" if status == "COMPLETED" else "FAILED",
            evidence=evidence,
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise

    return {
        "received": True,
        "operation": "REFUND",
        "refund_id": refund_id,
        "status": "CONFIRMED" if status == "COMPLETED" else "FAILED",
    }


@router.post("/flutterwave/webhook")
@limiter.limit("120/minute")
async def flutterwave_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Verify a Flutterwave v4 signature and authoritative charge before applying an event."""
    raw_body = await request.body()
    signature = request.headers.get("flutterwave-signature", "")
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_webhook", "message": "Webhook body must be valid JSON."},
        ) from None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_webhook", "message": "Flutterwave webhook payload is invalid."},
        )
    try:
        adapter = payment_providers.get("FLUTTERWAVE")
    except PaymentProviderUnavailable:
        raise HTTPException(
            status_code=503,
            detail={"code": "payment_provider_unavailable", "message": "Flutterwave is not configured."},
        ) from None
    if not adapter.verify_webhook(raw_body, signature):
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_signature", "message": "Flutterwave webhook signature is invalid."},
        )
    data = payload["data"]
    charge_id = str(data.get("id", ""))
    if payload.get("type") != "charge.completed" or not charge_id:
        return {"received": True, "ignored": True}
    try:
        verified = adapter.verify_transaction(charge_id)
    except (ValueError, RuntimeError):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "transaction_verification_unavailable",
                "message": "Flutterwave charge verification could not be completed.",
            },
        ) from None

    reference = verified.get("reference")
    currency = str(verified.get("currency", "")).upper()
    try:
        amount = Decimal(str(verified.get("amount")))
    except (InvalidOperation, TypeError):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_verified_amount", "message": "Flutterwave returned an invalid transaction amount."},
        ) from None

    webhook_reference = str(data.get("reference", ""))
    if (
        str(verified.get("id", "")) != charge_id
        or not reference
        or webhook_reference != str(reference)
        or currency != "UGX"
        or not amount.is_finite()
        or amount != amount.to_integral_value()
        or amount <= 0
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "transaction_details_mismatch",
                "message": "Flutterwave charge details did not match the webhook.",
            },
        )

    outcome = str(verified.get("status", "")).lower()
    if outcome not in {"succeeded", "failed", "voided"}:
        return {"received": True, "status": "pending"}

    normalized = PaymentWebhookIn(
        provider_reference=str(reference),
        provider_event_id=charge_id,
        amount_ugx=int(amount),
        currency="UGX",
        status="SUCCESSFUL" if outcome == "succeeded" else "FAILED",
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
    if provider_name == "PAWAPAY":
        return _reconcile_pawapay_deposit(payload.provider_reference, db)
    if not adapter.verify_webhook(await request.body(), signature):
        raise HTTPException(status_code=401, detail={"code": "invalid_signature", "message": "Payment callback signature is invalid."})
    return _apply_payment_event(provider_name, payload, db)


def _apply_payment_event(provider_name: str, payload: PaymentWebhookIn, db: Session) -> dict:
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
        elif payment.status == "SUCCESSFUL" and payment_event.disposition == "APPLIED":
            for allocation in allocate_successful_payment_for_order(db, payment_id=payment.id):
                post_payable_credit_for_payment_allocation(db, allocation_id=allocation.id)
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


@router.post("/orders/{order_id}/refresh")
@limiter.limit("30/minute")
def refresh_order_payments(
    order_id: UUID,
    request: Request,
    principal: Principal = Depends(require_roles("CUSTOMER", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    order = db.get(Order, order_id)
    if order is None or (principal.user.role == "CUSTOMER" and order.customer_id != principal.user.id):
        raise HTTPException(status_code=404, detail={"code": "order_not_found", "message": "Order was not found."})
    pending = db.scalars(select(Payment).where(
        Payment.order_id == order.id,
        Payment.provider == "PAWAPAY",
        Payment.status.in_(["PENDING", "UNKNOWN"]),
    ).order_by(Payment.created_at.desc()).limit(5)).all()
    for payment in pending:
        _reconcile_pawapay_deposit(str(payment.provider_reference or payment.attempt_reference), db)
    db.refresh(order)
    return {"order_id": order.id, "payment_status": order.payment_status}


@router.post("/{payment_id}/refresh")
@limiter.limit("30/minute")
def refresh_payment(
    payment_id: UUID,
    request: Request,
    principal: Principal = Depends(require_roles("CUSTOMER", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    """Recover missed callbacks using only the provider's verified deposit record."""
    payment = db.get(Payment, payment_id)
    if payment is None or (principal.user.role == "CUSTOMER" and payment.customer_id != principal.user.id):
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Payment was not found."})
    if payment.provider == "PAWAPAY" and payment.status in {"PENDING", "UNKNOWN"}:
        _reconcile_pawapay_deposit(str(payment.provider_reference or payment.attempt_reference), db)
        db.refresh(payment)
    return get_payment(payment_id, principal, db)


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
