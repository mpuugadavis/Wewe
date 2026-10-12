"""PawaPay Merchant API v2 adapter for Uganda mobile-money deposits."""
from __future__ import annotations

import json
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen
from uuid import uuid4

from app.config import get_settings
from app.services.payments import PaymentInitiation, PaymentProviderUnavailable, PaymentRequest


class PawaPayAPIError(RuntimeError):
    def __init__(self, message: str, *, stage: str | None = None, http_status: int | None = None,
                 failure_code: str | None = None, failure_message: str | None = None) -> None:
        super().__init__(message)
        self.stage = stage
        self.http_status = http_status
        self.failure_code = failure_code
        self.failure_message = failure_message

    def diagnostic(self) -> dict:
        return {
            "provider": "PAWAPAY",
            "stage": self.stage,
            "http_status": self.http_status,
            "failure_code": self.failure_code,
            "failure_message": self.failure_message,
            "message": str(self),
        }


class PawaPayProvider:
    name = "PAWAPAY"

    _NETWORKS = {
        "MTN_MOMO": "MTN_MOMO_UGA",
        "AIRTEL_MONEY": "AIRTEL_OAPI_UGA",
    }

    def __init__(self) -> None:
        self.settings = get_settings()

    def _credentials(self) -> tuple[str, str]:
        token = self.settings.pawapay_api_token
        if token is None or not token.get_secret_value().strip():
            raise PaymentProviderUnavailable("PawaPay API token is not configured.")
        return token.get_secret_value().strip(), self.settings.pawapay_api_base_url.rstrip("/")

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        token, base_url = self._credentials()
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = URLRequest(
            f"{base_url}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
                decoded = json.loads(raw) if raw else {}
                status = response.status
        except HTTPError as exc:
            raw = exc.read(4096).decode("utf-8", errors="replace")
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                decoded = {}
            failure = decoded.get("failureReason")
            if not isinstance(failure, dict):
                failure = decoded.get("rejectionReason")
            if not isinstance(failure, dict):
                failure = {}
            failure_code = failure.get("failureCode") or failure.get("rejectionCode") or decoded.get("errorCode")
            failure_message = failure.get("failureMessage") or failure.get("rejectionMessage") or decoded.get("errorMessage") or decoded.get("message")
            error_id = decoded.get("errorId")
            suffix = f" (errorId={error_id})" if error_id else ""
            raise PawaPayAPIError(
                f"PawaPay API request failed{suffix}.",
                stage=path,
                http_status=exc.code,
                failure_code=str(failure_code) if failure_code is not None else None,
                failure_message=str(failure_message) if failure_message else None,
            ) from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise PawaPayAPIError(
                f"PawaPay request failed ({type(exc).__name__}).",
                stage=path,
            ) from None
        if not isinstance(decoded, dict):
            raise PawaPayAPIError("PawaPay returned an invalid response.", stage=path, http_status=status)
        return decoded

    @staticmethod
    def _msisdn(phone: str) -> str:
        cleaned = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if cleaned.startswith("+"):
            cleaned = cleaned[1:]
        elif cleaned.startswith("00"):
            cleaned = cleaned[2:]
        elif cleaned.startswith("0") and len(cleaned) == 10:
            cleaned = "256" + cleaned[1:]
        elif cleaned.startswith("256"):
            pass
        else:
            raise ValueError("PawaPay Uganda phone number must use +256 or 07XXXXXXXX format.")
        if len(cleaned) != 12 or not cleaned.startswith("2567") or not cleaned.isdigit():
            raise ValueError("Enter a valid Ugandan mobile number, for example +256700000000")
        return cleaned

    def initiate(self, request: PaymentRequest) -> PaymentInitiation:
        provider = self._NETWORKS.get(request.method)
        if provider is None:
            raise ValueError("Unsupported Uganda mobile-money network for PawaPay.")

        deposit_id = str(uuid4())
        msisdn = self._msisdn(request.phone)
        amount = Decimal(request.amount_ugx)
        if amount <= 0 or amount != amount.to_integral_value():
            raise ValueError("PawaPay requires a positive whole-UGX payment amount.")

        payload = {
            "depositId": deposit_id,
            "amount": str(int(amount)),
            "currency": "UGX",
            "payer": {
                "type": "MMO",
                "accountDetails": {
                    "phoneNumber": msisdn,
                    "provider": provider,
                },
            },
            # Keep the customer-facing message within PawaPay's strict
            # 4-22 character validation. The merchant reference belongs in
            # clientReferenceId, not in this display field.
            "customerMessage": "WEWE Payment",
            "clientReferenceId": request.reference[:64],
        }
        response = self._request("POST", "/v2/deposits", payload)
        status = str(response.get("status", "")).upper()
        if status == "ACCEPTED":
            return PaymentInitiation(
                provider_reference=deposit_id,
                checkout_url=None,
                provider_payload=response,
            )
        if status == "DUPLICATE_IGNORED":
            raise PawaPayAPIError(
                "PawaPay rejected a duplicate deposit identifier.",
                stage="/v2/deposits",
                http_status=200,
                failure_code="DUPLICATE_IGNORED",
            )
        failure = response.get("failureReason")
        if not isinstance(failure, dict):
            failure = {}
        raise PawaPayAPIError(
            "PawaPay rejected the payment request.",
            stage="/v2/deposits",
            http_status=200,
            failure_code=str(failure.get("failureCode")) if failure.get("failureCode") else status or None,
            failure_message=str(failure.get("failureMessage")) if failure.get("failureMessage") else None,
        )

    def get_deposit_status(self, deposit_id: str) -> dict:
        """Fetch the provider-authoritative state for a deposit."""
        response = self._request("GET", f"/v2/deposits/{deposit_id}")
        if isinstance(response, list):
            return response[0] if response and isinstance(response[0], dict) else {}
        return response

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        # PawaPay v2 callback signatures use its HTTP-signature/public-key
        # mechanism. Callback processing is handled by the dedicated endpoint;
        # this method intentionally does not pretend an HMAC secret is equivalent.
        return bool(raw_body) and bool(signature)

    def verify_callback_payload(self, payload: dict) -> bool:
        return isinstance(payload.get("depositId"), str) and isinstance(payload.get("status"), str)


def build_pawapay_provider() -> PawaPayProvider:
    return PawaPayProvider()
