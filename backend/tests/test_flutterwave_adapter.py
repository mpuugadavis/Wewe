import json
from io import BytesIO

import pytest

from app.services.flutterwave import FlutterwaveError, FlutterwaveProvider
from app.services.payments import PaymentRequest


class FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def provider() -> FlutterwaveProvider:
    return FlutterwaveProvider(
        secret_key="FLWSECK_TEST_example",
        webhook_secret_hash="a" * 40,
        api_base_url="https://api.flutterwave.com/v3",
    )


def test_webhook_secret_hash_is_compared():
    adapter = provider()
    assert adapter.verify_webhook(b'{"event":"charge.completed"}', "a" * 40)
    assert not adapter.verify_webhook(b'{"event":"charge.completed"}', "wrong")
    assert not adapter.verify_webhook(b"body", "")


def test_initiate_uses_secure_hosted_checkout(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse({"status": "success", "data": {"link": "https://checkout.flutterwave.com/pay/abc"}})

    monkeypatch.setattr("app.services.flutterwave.urlopen", fake_urlopen)
    result = provider().initiate(
        PaymentRequest(
            reference="WEWE-ORDER-1001-ABCDEF12",
            amount_ugx=35000,
            currency="UGX",
            phone="+256700000000",
            callback_url="https://wewe.example/checkout/return",
            email="student@example.com",
        )
    )
    request = captured["request"]
    body = json.loads(request.data.decode())
    assert request.method == "POST"
    assert request.full_url.endswith("/payments")
    assert request.get_header("Authorization") == "Bearer FLWSECK_TEST_example"
    assert body["tx_ref"] == "WEWE-ORDER-1001-ABCDEF12"
    assert body["amount"] == "35000"
    assert body["currency"] == "UGX"
    assert body["redirect_url"] == "https://wewe.example/checkout/return"
    assert body["customer"]["email"] == "student@example.com"
    assert result.checkout_url == "https://checkout.flutterwave.com/pay/abc"
    assert result.provider_reference == "WEWE-ORDER-1001-ABCDEF12"


def test_initiate_rejects_missing_email_before_network(monkeypatch):
    def unexpected_urlopen(*args, **kwargs):
        pytest.fail("No network request should be made without customer email")

    monkeypatch.setattr("app.services.flutterwave.urlopen", unexpected_urlopen)
    with pytest.raises(FlutterwaveError, match="email address is required"):
        provider().initiate(
            PaymentRequest(
                reference="WEWE-ORDER-1001-ABCDEF12",
                amount_ugx=35000,
                currency="UGX",
                phone="+256700000000",
                callback_url="https://wewe.example/checkout/return",
            )
        )


def test_verify_transaction_returns_authoritative_data(monkeypatch):
    def fake_urlopen(request, timeout):
        assert request.method == "GET"
        assert request.full_url.endswith("/transactions/12345/verify")
        return FakeResponse({
            "status": "success",
            "data": {
                "id": 12345,
                "tx_ref": "WEWE-ORDER-1001-ABCDEF12",
                "status": "successful",
                "amount": 35000,
                "currency": "UGX",
            },
        })

    monkeypatch.setattr("app.services.flutterwave.urlopen", fake_urlopen)
    verified = provider().verify_transaction(12345)
    assert verified["status"] == "successful"
    assert verified["amount"] == 35000
    assert verified["currency"] == "UGX"


def test_verify_transaction_rejects_non_numeric_id():
    with pytest.raises(FlutterwaveError, match="transaction ID is invalid"):
        provider().verify_transaction("not-a-transaction-id")
