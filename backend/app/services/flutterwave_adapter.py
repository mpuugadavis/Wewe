"""Flutterwave Uganda mobile-money adapter (v3 API)."""
from __future__ import annotations

import hmac
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, urlopen

from app.config import get_settings
from app.services.payments import PaymentInitiation, PaymentProviderUnavailable, PaymentRequest


class FlutterwaveAPIError(RuntimeError):
    """The Flutterwave API could not complete a request safely."""


class FlutterwaveProvider:
    name = "FLUTTERWAVE"

    def __init__(self) -> None:
        self.settings = get_settings()

    def _secret(self) -> str:
        value = self.settings.flutterwave_secret_key
        if value is None:
            raise PaymentProviderUnavailable("Flutterwave sandbox credentials are not configured.")
        return value.get_secret_value()

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        base = self.settings.flutterwave_api_base_url.rstrip("/")
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = URLRequest(
            f"{base}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self._secret()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=20) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # Do not include request headers or credentials in logs/errors.
            detail = exc.read(2048).decode("utf-8", errors="replace")
            raise FlutterwaveAPIError(f"Flutterwave returned HTTP {exc.code}: {detail}") from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise FlutterwaveAPIError(f"Flutterwave request failed ({type(exc).__name__}).") from None
        if not isinstance(decoded, dict):
            raise FlutterwaveAPIError("Flutterwave returned an invalid response.")
        return decoded

    def initiate(self, request: PaymentRequest) -> PaymentInitiation:
        email = (request.customer_email or "").strip()
        if not email:
            raise ValueError("An email address is required for Flutterwave mobile-money checkout.")
        network = {"MTN_MOMO": "MTN", "AIRTEL_MONEY": "AIRTEL"}.get(request.method)
        if network is None:
            raise ValueError("Unsupported Uganda mobile-money network.")
        response = self._request(
            "POST",
            "/charges?" + urlencode({"type": "mobile_money_uganda"}),
            {
                "phone_number": request.phone,
                "network": network,
                "amount": request.amount_ugx,
                "currency": "UGX",
                "email": email,
                "redirect_url": self.settings.flutterwave_redirect_url,
                "tx_ref": request.reference,
                "fullname": request.customer_name or "WEWE customer",
                "meta": {"wewe_payment_reference": request.reference, "wewe_method": request.method},
            },
        )
        if response.get("status") != "success":
            raise FlutterwaveAPIError("Flutterwave did not accept the mobile-money payment request.")
        meta = response.get("meta") or {}
        authorization = meta.get("authorization") or {}
        checkout_url = authorization.get("redirect")
        if not isinstance(checkout_url, str) or not checkout_url.startswith("https://"):
            raise FlutterwaveAPIError("Flutterwave did not return a secure payment confirmation URL.")
        return PaymentInitiation(
            provider_reference=request.reference,
            checkout_url=checkout_url,
            provider_payload={"status": response.get("status"), "message": response.get("message")},
        )

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        configured = self.settings.flutterwave_webhook_secret_hash
        if configured is None or not signature:
            return False
        expected = configured.get_secret_value()
        return hmac.compare_digest(expected.encode("utf-8"), signature.encode("utf-8"))

    def verify_transaction(self, transaction_id: str) -> dict:
        if not transaction_id.isdigit():
            raise ValueError("Flutterwave transaction ID must be numeric.")
        response = self._request("GET", f"/transactions/{transaction_id}/verify")
        data = response.get("data")
        if response.get("status") != "success" or not isinstance(data, dict):
            raise FlutterwaveAPIError("Flutterwave could not verify the transaction.")
        return data


def build_flutterwave_provider() -> FlutterwaveProvider:
    return FlutterwaveProvider()
