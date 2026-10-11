"""Flutterwave Standard checkout adapter for WEWE.

This adapter uses Flutterwave's v3 REST API and never stores secret keys in
source control. Payment success is not inferred from the browser redirect.
"""
from __future__ import annotations

import hmac
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import get_settings
from app.services.payments import PaymentInitiation, PaymentRequest

logger = logging.getLogger(__name__)


class FlutterwaveError(RuntimeError):
    """A safe, non-secret-bearing Flutterwave API error."""


class FlutterwaveProvider:
    name = "FLUTTERWAVE"

    def __init__(
        self,
        secret_key: str,
        webhook_secret_hash: str,
        api_base_url: str = "https://api.flutterwave.com/v3",
        timeout_seconds: float = 15.0,
    ) -> None:
        self._secret_key = secret_key
        self._webhook_secret_hash = webhook_secret_hash
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self._api_base_url}/{path.lstrip('/')}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self._secret_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            logger.warning("Flutterwave API returned HTTP %s for %s", exc.code, path)
            raise FlutterwaveError(f"Flutterwave API request failed (HTTP {exc.code}).") from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            logger.warning("Flutterwave API request failed for %s: %s", path, type(exc).__name__)
            raise FlutterwaveError("Flutterwave could not be reached; payment outcome may be unknown.") from None
        if not isinstance(result, dict) or result.get("status") != "success":
            raise FlutterwaveError("Flutterwave did not accept the request.")
        return result

    def initiate(self, request: PaymentRequest) -> PaymentInitiation:
        email = getattr(request, "email", None)
        if not email:
            raise FlutterwaveError("A customer email address is required for Flutterwave checkout.")
        response = self._request(
            "POST",
            "payments",
            {
                "tx_ref": request.reference,
                "amount": str(request.amount_ugx),
                "currency": request.currency,
                "redirect_url": request.callback_url,
                "payment_options": "mobilemoneyuganda",
                "customer": {"email": email, "phonenumber": request.phone},
                "customizations": {"title": "WEWE Campus Shopping", "description": "WEWE order payment"},
                "meta": {"wewe_payment_reference": request.reference},
            },
        )
        data = response.get("data") or {}
        checkout_url = data.get("link")
        if not isinstance(checkout_url, str) or not checkout_url.startswith("https://"):
            raise FlutterwaveError("Flutterwave did not return a valid secure checkout URL.")
        return PaymentInitiation(
            provider_reference=request.reference,
            checkout_url=checkout_url,
            provider_payload={"provider": self.name, "checkout_created": True},
        )

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        # Flutterwave v3 sends the configured secret hash as the verif-hash header.
        return bool(
            self._webhook_secret_hash
            and signature
            and hmac.compare_digest(signature, self._webhook_secret_hash)
        )

    def verify_transaction(self, transaction_id: int | str) -> dict:
        if not str(transaction_id).isdigit():
            raise FlutterwaveError("Flutterwave transaction ID is invalid.")
        result = self._request("GET", f"transactions/{transaction_id}/verify")
        data = result.get("data")
        if not isinstance(data, dict):
            raise FlutterwaveError("Flutterwave verification response was incomplete.")
        return data


def configure_flutterwave_provider() -> None:
    """Register Flutterwave for both mobile-money checkout choices when configured."""
    settings = get_settings()
    if settings.payment_mode != "EXTERNAL":
        return
    if not settings.flutterwave_secret_key or not settings.flutterwave_webhook_secret_hash:
        logger.warning("External payments enabled but Flutterwave credentials are incomplete")
        return
    provider = FlutterwaveProvider(
        secret_key=settings.flutterwave_secret_key.get_secret_value(),
        webhook_secret_hash=settings.flutterwave_webhook_secret_hash.get_secret_value(),
        api_base_url=settings.flutterwave_api_base_url,
    )
    from app.services.payments import payment_providers

    payment_providers.register("MTN_MOMO", provider)
    payment_providers.register("AIRTEL_MONEY", provider)
    payment_providers.register("FLUTTERWAVE", provider)
