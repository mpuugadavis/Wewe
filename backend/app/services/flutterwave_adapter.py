"""Flutterwave Uganda mobile-money adapter using the v4 OAuth API."""
from __future__ import annotations

import base64
import hmac
import json
import threading
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, urlopen

from app.config import get_settings
from app.services.payments import PaymentInitiation, PaymentProviderUnavailable, PaymentRequest


FLUTTERWAVE_TOKEN_URL = "https://idp.flutterwave.com/realms/flutterwave/protocol/openid-connect/token"


class FlutterwaveAPIError(RuntimeError):
    """A safe, structured error returned by Flutterwave."""

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        http_status: int | None = None,
        provider_code: str | None = None,
        provider_type: str | None = None,
        validation_errors: list[dict] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.http_status = http_status
        self.provider_code = provider_code
        self.provider_type = provider_type
        self.validation_errors = validation_errors or []
        self.request_id = request_id

    def diagnostic(self) -> dict:
        return {
            "provider": "FLUTTERWAVE",
            "stage": self.stage,
            "http_status": self.http_status,
            "provider_code": self.provider_code,
            "provider_type": self.provider_type,
            "message": str(self),
            "validation_errors": self.validation_errors,
            "request_id": self.request_id,
        }


class FlutterwaveProvider:
    name = "FLUTTERWAVE"

    def __init__(self) -> None:
        self.settings = get_settings()
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0
        self._token_lock = threading.Lock()

    def _credentials(self) -> tuple[str, str]:
        client_id = (self.settings.flutterwave_client_id or "").strip()
        client_secret = self.settings.flutterwave_client_secret
        if not client_id or client_secret is None:
            raise PaymentProviderUnavailable("Flutterwave v4 sandbox credentials are not configured.")
        return client_id, client_secret.get_secret_value()

    def _get_access_token(self) -> str:
        now = time.monotonic()
        if self._access_token and now < self._access_token_expires_at - 60:
            return self._access_token

        with self._token_lock:
            now = time.monotonic()
            if self._access_token and now < self._access_token_expires_at - 60:
                return self._access_token

            client_id, client_secret = self._credentials()
            body = urlencode(
                {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "client_credentials",
                }
            ).encode("utf-8")
            request = URLRequest(
                FLUTTERWAVE_TOKEN_URL,
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=20) as response:
                    decoded = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                detail = exc.read(2048).decode("utf-8", errors="replace")
                raise FlutterwaveAPIError(f"Flutterwave OAuth returned HTTP {exc.code}: {detail}") from None
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                raise FlutterwaveAPIError(f"Flutterwave OAuth request failed ({type(exc).__name__}).") from None

            token = decoded.get("access_token") if isinstance(decoded, dict) else None
            expires_in = decoded.get("expires_in", 600) if isinstance(decoded, dict) else 600
            if not isinstance(token, str) or not token:
                raise FlutterwaveAPIError("Flutterwave OAuth did not return an access token.")
            try:
                expires = float(expires_in)
            except (TypeError, ValueError):
                expires = 600.0
            self._access_token = token
            self._access_token_expires_at = time.monotonic() + max(expires, 60.0)
            return token

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict:
        base = self.settings.flutterwave_api_base_url.rstrip("/")
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Trace-Id": str(uuid.uuid4()),
        }
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key
        request = URLRequest(f"{base}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
                decoded = json.loads(raw)
        except HTTPError as exc:
            raw = exc.read(4096).decode("utf-8", errors="replace")
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                decoded = None
            error = decoded.get("error") if isinstance(decoded, dict) else None
            if not isinstance(error, dict):
                error = {}
            validation_errors = error.get("validation_errors")
            if not isinstance(validation_errors, list):
                validation_errors = []
            request_id = (
                (decoded.get("request_id") if isinstance(decoded, dict) else None)
                or error.get("request_id")
                or error.get("requestId")
            )
            message = error.get("message") or (
                decoded.get("message") if isinstance(decoded, dict) else None
            ) or "Flutterwave rejected the request."
            raise FlutterwaveAPIError(
                str(message),
                stage=path,
                http_status=exc.code,
                provider_code=str(error.get("code")) if error.get("code") is not None else None,
                provider_type=str(error.get("type")) if error.get("type") is not None else None,
                validation_errors=[item for item in validation_errors if isinstance(item, dict)],
                request_id=str(request_id) if request_id else None,
            ) from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise FlutterwaveAPIError(
                f"Flutterwave request failed ({type(exc).__name__}).",
                stage=path,
            ) from None
        if not isinstance(decoded, dict):
            raise FlutterwaveAPIError("Flutterwave returned an invalid response.", stage=path)
        if decoded.get("status") == "failed":
            error = decoded.get("error")
            if not isinstance(error, dict):
                error = {}
            validation_errors = error.get("validation_errors")
            if not isinstance(validation_errors, list):
                validation_errors = []
            request_id = decoded.get("request_id") or error.get("request_id") or error.get("requestId")
            message = error.get("message") or decoded.get("message") or "Flutterwave rejected the request."
            raise FlutterwaveAPIError(
                str(message),
                stage=path,
                http_status=200,
                provider_code=str(error.get("code")) if error.get("code") is not None else None,
                provider_type=str(error.get("type")) if error.get("type") is not None else None,
                validation_errors=[item for item in validation_errors if isinstance(item, dict)],
                request_id=str(request_id) if request_id else None,
            )
        return decoded

    @staticmethod
    def _split_name(name: str | None) -> dict[str, str]:
        parts = (name or "WEWE Customer").strip().split()
        if not parts:
            return {"first": "WEWE"}
        return {"first": parts[0], "last": parts[-1] if len(parts) > 1 else parts[0]}

    @staticmethod
    def _phone_parts(phone: str) -> tuple[str, str]:
        cleaned = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if cleaned.startswith("+"):
            digits = cleaned[1:]
        elif cleaned.startswith("00"):
            digits = cleaned[2:]
        else:
            digits = cleaned
        if digits.startswith("256"):
            return "256", digits[3:]
        if digits.startswith("0"):
            return "256", digits[1:]
        raise ValueError("Flutterwave Uganda mobile-money phone must use +256 or 07XXXXXXXX format.")

    def initiate(self, request: PaymentRequest) -> PaymentInitiation:
        email = (request.customer_email or "").strip()
        if not email:
            raise ValueError("An email address is required for Flutterwave mobile-money checkout.")
        network = {"MTN_MOMO": "MTN", "AIRTEL_MONEY": "AIRTEL"}.get(request.method)
        if network is None:
            raise ValueError("Unsupported Uganda mobile-money network.")
        country_code, number = self._phone_parts(request.phone)

        customer_response = self._request(
            "POST",
            "/customers",
            {
                "email": email,
                "name": self._split_name(request.customer_name),
                "phone": {"country_code": country_code, "number": number},
            },
            idempotency_key=f"wewe-customer-{request.reference}",
        )
        customer = customer_response.get("data") if isinstance(customer_response, dict) else None
        customer_id = customer.get("id") if isinstance(customer, dict) else None
        if customer_response.get("status") != "success" or not isinstance(customer_id, str):
            raise FlutterwaveAPIError("Flutterwave did not create the customer profile.", stage="/customers")

        method_response = self._request(
            "POST",
            "/payment-methods",
            {
                "type": "mobile_money",
                "mobile_money": {
                    "country_code": country_code,
                    "network": network,
                    "phone_number": number,
                },
            },
            idempotency_key=f"wewe-method-{request.reference}",
        )
        payment_method = method_response.get("data") if isinstance(method_response, dict) else None
        payment_method_id = payment_method.get("id") if isinstance(payment_method, dict) else None
        if method_response.get("status") != "success" or not isinstance(payment_method_id, str):
            raise FlutterwaveAPIError("Flutterwave did not create the mobile-money payment method.", stage="/payment-methods")

        charge_response = self._request(
            "POST",
            "/charges",
            {
                "amount": request.amount_ugx,
                "currency": "UGX",
                "reference": request.reference,
                "customer_id": customer_id,
                "payment_method_id": payment_method_id,
                "meta": {
                    "wewe_payment_reference": request.reference,
                    "wewe_method": request.method,
                },
            },
            idempotency_key=f"wewe-charge-{request.reference}",
        )
        data = charge_response.get("data") if isinstance(charge_response, dict) else None
        charge_id = data.get("id") if isinstance(data, dict) else None
        if charge_response.get("status") not in {"success", "pending"} or not isinstance(charge_id, str):
            raise FlutterwaveAPIError("Flutterwave did not create the mobile-money charge.", stage="/charges")

        checkout_url = None
        next_action = data.get("next_action") if isinstance(data, dict) else None
        if isinstance(next_action, dict):
            redirect = next_action.get("redirect_url")
            if isinstance(redirect, dict):
                candidate = redirect.get("url")
                if isinstance(candidate, str) and candidate.startswith("https://"):
                    checkout_url = candidate

        return PaymentInitiation(
            provider_reference=request.reference,
            checkout_url=checkout_url,
            provider_payload={
                "charge_id": charge_id,
                "customer_id": customer_id,
                "payment_method_id": payment_method_id,
                "status": data.get("status") if isinstance(data, dict) else None,
            },
        )

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        configured = self.settings.flutterwave_webhook_secret_hash
        if configured is None or not signature:
            return False
        digest = hmac.new(
            configured.get_secret_value().encode("utf-8"),
            raw_body,
            "sha256",
        ).digest()
        expected = base64.b64encode(digest).decode("ascii")
        return hmac.compare_digest(expected, signature)

    def verify_transaction(self, transaction_id: str) -> dict:
        if not transaction_id or len(transaction_id) > 180:
            raise ValueError("Flutterwave charge ID is invalid.")
        response = self._request("GET", f"/charges/{transaction_id}")
        data = response.get("data")
        if response.get("status") != "success" or not isinstance(data, dict):
            raise FlutterwaveAPIError("Flutterwave could not verify the charge.")
        return data


def build_flutterwave_provider() -> FlutterwaveProvider:
    return FlutterwaveProvider()
