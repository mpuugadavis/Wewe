from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.services.flutterwave_adapter import FlutterwaveProvider
from app.services.payments import PaymentRequest


def make_provider() -> FlutterwaveProvider:
    provider = FlutterwaveProvider.__new__(FlutterwaveProvider)
    provider.settings = SimpleNamespace(
        flutterwave_secret_key=SecretStr("FLWSECK_TEST-example"),
        flutterwave_webhook_secret_hash=SecretStr("sandbox-webhook-hash"),
        flutterwave_redirect_url="http://localhost:5500/",
        flutterwave_api_base_url="https://api.flutterwave.com/v3",
    )
    return provider


@pytest.mark.parametrize(
    ("method", "expected_network"),
    [("MTN_MOMO", "MTN"), ("AIRTEL_MONEY", "AIRTEL")],
)
def test_initiate_uses_selected_uganda_network(method, expected_network):
    provider = make_provider()
    captured = {}

    def fake_request(http_method, path, payload=None):
        captured.update(method=http_method, path=path, payload=payload)
        return {
            "status": "success",
            "message": "Charge initiated",
            "meta": {"authorization": {"redirect": "https://checkout.flutterwave.com/test"}},
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

    assert captured["method"] == "POST"
    assert captured["path"] == "/charges?type=mobile_money_uganda"
    assert captured["payload"]["network"] == expected_network
    assert captured["payload"]["amount"] == 1500
    assert captured["payload"]["currency"] == "UGX"
    assert captured["payload"]["tx_ref"] == "WEWE-TEST-12345"
    assert result.provider_reference == "WEWE-TEST-12345"
    assert result.checkout_url == "https://checkout.flutterwave.com/test"


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


def test_webhook_requires_configured_secret_hash():
    provider = make_provider()
    assert provider.verify_webhook(b'{"event":"charge.completed"}', "sandbox-webhook-hash")
    assert not provider.verify_webhook(b'{"event":"charge.completed"}', "wrong-hash")
    assert not provider.verify_webhook(b'{"event":"charge.completed"}', "")
