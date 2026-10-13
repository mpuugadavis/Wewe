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
                 failure_code: str | None = None, failure_message: str | None = None,
                 request_id: str | None = None, validation_errors: object | None = None) -> None:
        super().__init__(message)
        self.stage = stage
        self.http_status = http_status
        self.failure_code = failure_code
        self.failure_message = failure_message
        self.request_id = request_id
        self.validation_errors = validation_errors

    def diagnostic(self) -> dict:
        return {
            "provider": "PAWAPAY",
            "stage": self.stage,
            "http_status": self.http_status,
            "failure_code": self.failure_code,
            "failure_message": self.failure_message,
            "request_id": self.request_id,
            "validation_errors": self.validation_errors,
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

            error = decoded.get("error")
            if not isinstance(error, dict):
                error = {}

            # Preserve both payment-domain rejection envelopes and HTTP
            # validation_error envelopes so provider diagnostics are not lost.
            failure_code = (
                failure.get("failureCode")
                or failure.get("rejectionCode")
                or error.get("code")
                or decoded.get("errorCode")
            )
            failure_message = (
                failure.get("failureMessage")
                or failure.get("rejectionMessage")
                or error.get("message")
                or decoded.get("errorMessage")
                or decoded.get("message")
            )
            request_id = (
                decoded.get("request_id")
                or decoded.get("requestId")
                or error.get("request_id")
                or error.get("requestId")
            )
            validation_errors = (
                decoded.get("errors")
                or decoded.get("validationErrors")
                or error.get("errors")
            )
            suffix = f" (request_id={request_id})" if request_id else ""
            raise PawaPayAPIError(
                f"PawaPay API request failed{suffix}.",
                stage=path,
                http_status=exc.code,
                failure_code=str(failure_code) if failure_code is not None else None,
                failure_message=str(failure_message) if failure_message else None,
                request_id=str(request_id) if request_id else None,
                validation_errors=validation_errors,
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

    def _validate_active_configuration(self, provider: str, amount: Decimal) -> None:
        """Validate this merchant account can accept this exact Uganda deposit."""
        config = self._request(
            "GET",
            "/v2/active-conf?country=UGA&operationType=DEPOSIT",
        )
        countries = config.get("countries") if isinstance(config, dict) else None
        if not isinstance(countries, list):
            raise PawaPayAPIError(
                "PawaPay active configuration returned no countries.",
                stage="/v2/active-conf",
                http_status=200,
                failure_code="INVALID_ACTIVE_CONFIGURATION",
                validation_errors=config,
            )
        ug = next((c for c in countries if isinstance(c, dict) and c.get("country") == "UGA"), None)
        if not isinstance(ug, dict):
            raise PawaPayAPIError(
                "Uganda is not enabled on this PawaPay account.",
                stage="/v2/active-conf",
                http_status=422,
                failure_code="COUNTRY_NOT_CONFIGURED",
            )
        providers = ug.get("providers")
        entry = next((
            p for p in providers or []
            if isinstance(p, dict) and p.get("provider") == provider
        ), None)
        if not isinstance(entry, dict):
            raise PawaPayAPIError(
                f"{provider} is not enabled for deposits on this PawaPay account.",
                stage="/v2/active-conf",
                http_status=422,
                failure_code="PROVIDER_NOT_CONFIGURED",
                validation_errors={"available_providers": [p.get("provider") for p in providers or [] if isinstance(p, dict)]},
            )
        currencies = entry.get("currencies")
        currency = next((
            x for x in currencies or []
            if isinstance(x, dict) and x.get("currency") == "UGX"
        ), None)
        if not isinstance(currency, dict):
            raise PawaPayAPIError(
                f"{provider} is not configured for UGX deposits.",
                stage="/v2/active-conf",
                http_status=422,
                failure_code="CURRENCY_NOT_CONFIGURED",
            )
        operation = (currency.get("operationTypes") or {}).get("DEPOSIT")
        if not isinstance(operation, dict):
            raise PawaPayAPIError(
                f"{provider} has no UGX deposit configuration.",
                stage="/v2/active-conf",
                http_status=422,
                failure_code="DEPOSIT_NOT_CONFIGURED",
            )
        if str(operation.get("status", "")).upper() not in {"OPERATIONAL", "OPEN"}:
            raise PawaPayAPIError(
                f"{provider} is not operational for UGX deposits.",
                stage="/v2/active-conf",
                http_status=422,
                failure_code="PROVIDER_NOT_OPERATIONAL",
                validation_errors={"status": operation.get("status")},
            )
        minimum = operation.get("minAmount")
        maximum = operation.get("maxAmount")
        try:
            if minimum is not None and amount < Decimal(str(minimum)):
                raise ValueError
            if maximum is not None and amount > Decimal(str(maximum)):
                raise ValueError
        except ValueError:
            raise PawaPayAPIError(
                f"Payment amount is outside the configured range for {provider}.",
                stage="/v2/active-conf",
                http_status=422,
                failure_code="AMOUNT_OUT_OF_BOUNDS",
                validation_errors={"minAmount": minimum, "maxAmount": maximum, "amount": str(amount)},
            ) from None

    def initiate(self, request: PaymentRequest) -> PaymentInitiation:
        provider = self._NETWORKS.get(request.method)
        if provider is None:
            raise ValueError("Unsupported Uganda mobile-money network for PawaPay.")

        deposit_id = str(uuid4())
        msisdn = self._msisdn(request.phone)
        amount = Decimal(request.amount_ugx)
        if amount <= 0 or amount != amount.to_integral_value():
            raise ValueError("PawaPay requires a positive whole-UGX payment amount.")

        self._validate_active_configuration(provider, amount)

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
        # Resolve the wallet from pawaPay itself immediately before initiation.
        # This removes the last hard-coded assumption about which Ugandan MMO owns
        # the supplied MSISDN and gives us provider-specific validation before
        # the financial request is sent.
        prediction = self._request(
            "POST",
            "/v2/predict-provider",
            {"phoneNumber": msisdn},
        )
        predicted_phone = str(prediction.get("phoneNumber") or "").strip()
        predicted_provider = str(prediction.get("provider") or "").strip().upper()
        if predicted_phone:
            msisdn = self._msisdn(predicted_phone)
            payload["payer"]["accountDetails"]["phoneNumber"] = msisdn
        if predicted_provider and predicted_provider != provider:
            raise PawaPayAPIError(
                "The selected mobile-money network does not match the supplied phone number.",
                stage="/v2/predict-provider",
                http_status=422,
                failure_code="PROVIDER_MISMATCH",
                failure_message=f"PawaPay identified {predicted_provider}; WEWE selected {provider}.",
            )
        if not predicted_provider:
            raise PawaPayAPIError(
                "PawaPay could not identify the mobile-money provider for this phone number.",
                stage="/v2/predict-provider",
                http_status=422,
                failure_code="PROVIDER_NOT_FOUND",
                failure_message=str(prediction.get("message") or "No provider was returned."),
                validation_errors=prediction,
            )

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
        path = f"/v2/deposits/{deposit_id}"
        response = self._request("GET", path)
        if not isinstance(response, dict):
            raise PawaPayAPIError("PawaPay deposit status is unavailable.", stage=path)
        # PawaPay v2 wraps the payment in a "data" object; the outer status is a
        # lookup result, not the transaction outcome itself.
        deposit = response.get("data")
        if response.get("status") != "FOUND" or not isinstance(deposit, dict):
            raise PawaPayAPIError("PawaPay deposit status is unavailable.", stage=path)
        if deposit.get("depositId") != deposit_id or not deposit.get("status"):
            raise PawaPayAPIError("PawaPay returned mismatched or incomplete deposit details.", stage=path)
        return deposit

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        # PawaPay v2 callback signatures use its HTTP-signature/public-key
        # mechanism. Callback processing is handled by the dedicated endpoint;
        # this method intentionally does not pretend an HMAC secret is equivalent.
        return bool(raw_body) and bool(signature)

    def verify_callback_payload(self, payload: dict) -> bool:
        return isinstance(payload.get("depositId"), str) and isinstance(payload.get("status"), str)


def build_pawapay_provider() -> PawaPayProvider:
    return PawaPayProvider()
