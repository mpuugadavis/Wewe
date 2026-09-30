"""Deterministic, no-money payment providers for local Phase 4B testing.

These adapters deliberately never call a mobile-money network. They exercise the
same provider boundary used by real adapters so checkout/webhook/reconciliation
logic can be tested safely before provider credentials and onboarding exist.
"""
from __future__ import annotations

import hashlib
import hmac
from uuid import uuid4

from app.config import get_settings
from app.services.payments import PaymentInitiation, PaymentRequest


class SimulatedMobileMoneyProvider:
    """Local provider simulator for one online-payment method."""

    def __init__(self, name: str) -> None:
        if name not in {"MTN_MOMO", "AIRTEL_MONEY"}:
            raise ValueError("Unsupported simulated payment method")
        self.name = name

    def initiate(self, request: PaymentRequest) -> PaymentInitiation:
        if request.currency != "UGX":
            raise ValueError("WEWE simulated mobile money accepts UGX only")
        if request.amount_ugx <= 0:
            raise ValueError("Payment amount must be positive")
        if not request.phone.startswith("+"):
            raise ValueError("Customer phone must use international format")
        return PaymentInitiation(
            provider_reference=f"SIM-{self.name}-{uuid4()}",
            provider_payload={
                "environment": "SIMULATED",
                "method": self.name,
                "reference": request.reference,
                "amount_ugx": request.amount_ugx,
                "currency": request.currency,
                "phone": request.phone,
            },
        )

    def verify_webhook(self, raw_body: bytes, signature: str | None) -> bool:
        settings = get_settings()
        secret = settings.payment_webhook_secret.get_secret_value() if settings.payment_webhook_secret else settings.secret_key.get_secret_value()
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return bool(signature) and hmac.compare_digest(signature, expected)

    @staticmethod
    def sign_webhook(raw_body: bytes) -> str:
        settings = get_settings()
        secret = settings.payment_webhook_secret.get_secret_value() if settings.payment_webhook_secret else settings.secret_key.get_secret_value()
        return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def configure_simulated_providers() -> None:
    """Register both online-only methods for local/test environments."""
    from app.services.payments import payment_providers

    payment_providers.register("MTN_MOMO", SimulatedMobileMoneyProvider("MTN_MOMO"))
    payment_providers.register("AIRTEL_MONEY", SimulatedMobileMoneyProvider("AIRTEL_MONEY"))
