import json

from app.services.payment_sandbox import SimulatedMobileMoneyProvider
from app.services.payments import PaymentRequest


def test_simulated_mobile_money_provider_never_requires_external_network() -> None:
    provider = SimulatedMobileMoneyProvider("MTN_MOMO")
    initiation = provider.initiate(
        PaymentRequest(
            reference="WW-TEST-ATTEMPT",
            amount_ugx=27500,
            currency="UGX",
            phone="+256700000001",
            callback_url="http://localhost:8000/api/v1/payments/webhooks/MTN_MOMO",
        )
    )

    assert initiation.provider_reference.startswith("SIM-MTN_MOMO-")
    assert initiation.checkout_url is None
    assert initiation.provider_payload["environment"] == "SIMULATED"
    assert initiation.provider_payload["amount_ugx"] == 27500


def test_simulated_mobile_money_webhook_signature_round_trip() -> None:
    provider = SimulatedMobileMoneyProvider("AIRTEL_MONEY")
    body = json.dumps(
        {
            "provider_reference": "SIM-AIRTEL_MONEY-test",
            "provider_event_id": "event-001",
            "amount_ugx": 27500,
            "currency": "UGX",
            "status": "SUCCESSFUL",
        },
        separators=(",", ":"),
    ).encode()

    signature = provider.sign_webhook(body)

    assert provider.verify_webhook(body, signature)
    assert not provider.verify_webhook(body, "not-a-valid-signature")
    assert not provider.verify_webhook(body + b"x", signature)
