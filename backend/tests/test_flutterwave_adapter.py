from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.services.flutterwave_adapter import FlutterwaveProvider
from app.services.payments import PaymentRequest


def make_provider() -> FlutterwaveProvider:
    provider = FlutterwaveProvider.__new__(FlutterwaveProvider)
    provider.settings = SimpleNamespace(
        flutterwave_client_id="test-client-id",
        flutterwave_client_secret=SecretStr("test-client-secret"),
        flutterwave_webhook_secret_hash=SecretStr("sandbox-webhook-hash"),
        flutterwave_redirect_url="http://localhost:5500/",
        flutterwave_api_base_url="https://developersandbox-api.flutterwave.com",
    )
    provider._access_token = "test-access-token"
    provider._access_token_expires_at = 9_999_999_999.0
    return provider


@pytest.mark.parametrize(
    ("method", "expected_network"),
    [("MTN_MOMO", "MTN"), ("AIRTEL_MONEY", "AIRTEL")],
)
def test_initiate_uses_v4_uganda_mobile_money(method, expected_network):
    provider = make_provider()
    captured = []

    def fake_request(http_method, path, payload=None, *, idempotency_key=None):
        captured.append((http_method, path, payload, idempotency_key))
        if path == "/customers":
            return {"status": "success", "data": {"id": "cus_test"}}
        if path == "/payment-methods":
            return {"status": "success", "data": {"id": "pmd_test"}}
        assert path == "/charges"
        return {
            "status": "success",
            "message": "Charge created",
            "data": {
                "id": "chg_test",
                "status": "pending",
                "next_action": {
                    "redirect_url": {"url": "https://developersandbox.flutterwave.com/redirect"}
                },
            },
        }

    provider._request = fake_request
    result = provider.initiate(
        PaymentRequest(
            reference="WEWE-TEST-12345",
            amount_ugx=1500,
            currency="UGX",
            phone="+256700000000",
            callback_url="https://api.example.test/api/v1/payments/flutterwave/webhook",
            method=method,
            customer_email="customer@example.com",
            customer_name="WEWE Test Customer",
        )
    )

    assert [item[1] for item in captured] == ["/customers", "/payment-methods", "/charges"]
    payment_method_payload = captured[1][2]
    assert payment_method_payload["mobile_money"]["country_code"] == "256"
    assert payment_method_payload["mobile_money"]["network"] == expected_network
    assert payment_method_payload["mobile_money"]["phone_number"] == "700000000"
    charge_payload = captured[2][2]
    assert "redirect_url" not in charge_payload
    assert charge_payload["amount"] == 1500
    assert charge_payload["currency"] == "UGX"
    assert charge_payload["reference"] == "WEWE-TEST-12345"
    assert result.provider_reference == "WEWE-TEST-12345"
    assert result.checkout_url == "https://developersandbox.flutterwave.com/redirect"
    assert result.provider_payload["charge_id"] == "chg_test"


def test_initiate_requires_customer_email():
    provider = make_provider()
    with pytest.raises(ValueError, match="email address is required"):
        provider.initiate(
            PaymentRequest(
                reference="WEWE-TEST-12345",
                amount_ugx=1500,
                currency="UGX",
                phone="+256700000000",
                callback_url="https://api.example.test/api/v1/payments/flutterwave/webhook",
                method="MTN_MOMO",
            )
        )


def test_v4_webhook_signature_uses_hmac_sha256_base64():
    provider = make_provider()
    raw = b'{"type":"charge.completed","data":{"id":"chg_test"}}'
    import base64
    import hashlib
    import hmac

    expected = base64.b64encode(
        hmac.new(
            b"sandbox-webhook-hash",
            raw,
            hashlib.sha256,
        ).digest()
    ).decode("ascii")
    assert provider.verify_webhook(raw, expected)
    assert not provider.verify_webhook(raw, "wrong-signature")
    assert not provider.verify_webhook(raw, "")


def test_verify_transaction_uses_v4_charge_id():
    provider = make_provider()
    captured = {}

    def fake_request(method, path, payload=None, **kwargs):
        captured.update(method=method, path=path)
        return {
            "status": "success",
            "data": {
                "id": "chg_test",
                "reference": "WEWE-TEST-12345",
                "amount": 1500,
                "currency": "UGX",
                "status": "succeeded",
            },
        }

    provider._request = fake_request
    result = provider.verify_transaction("chg_test")
    assert captured == {"method": "GET", "path": "/charges/chg_test"}
    assert result["status"] == "succeeded"
