from uuid import uuid4
from unittest.mock import Mock

import pytest
from sqlalchemy import select, func

from app.models import PaymentEvent, RetailerPaymentAllocation, User
from app.schemas import CheckoutIn
from app.services.orders import create_order
from app.services.payments import payment_providers
from test_order_service import marketplace_fixture, _create_payment_for_order, _authorization


def setup_payment(database, monkeypatch):
    customer, point, _, _ = marketplace_fixture(database)
    order = create_order(database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "refresh-test")
    payment = _create_payment_for_order(database, order, customer)
    payment.provider = "PAWAPAY"
    payment.provider_reference = str(uuid4())
    database.commit()
    provider = Mock()
    provider.get_deposit_status.return_value = {"depositId": payment.provider_reference, "status": "COMPLETED", "amount": str(payment.amount_ugx), "currency": "UGX"}
    monkeypatch.setattr(payment_providers, "get", lambda _: provider)
    return customer, order, payment, provider


def test_refresh_recovers_missed_callback_once(client, database, monkeypatch):
    customer, order, payment, provider = setup_payment(database, monkeypatch)
    headers = _authorization(database, customer)
    url = f"/api/v1/payments/{payment.id}/refresh"
    for _ in range(2):
        result = client.post(url, headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "SUCCESSFUL"
    database.refresh(order)
    assert order.payment_status == "PAID"
    assert database.scalar(select(func.count()).select_from(PaymentEvent)) == 1
    assert database.scalar(select(func.count()).select_from(RetailerPaymentAllocation)) == 1
    provider.get_deposit_status.assert_called_once_with(payment.provider_reference)
    callback = client.post("/api/v1/payments/pawapay/deposit-callback", json={"depositId": payment.provider_reference, "status": "COMPLETED"})
    assert callback.status_code == 200
    assert callback.json()["duplicate"] is True


def test_refresh_cannot_access_other_customer_payment(client, database, monkeypatch):
    _, _, payment, provider = setup_payment(database, monkeypatch)
    other = User(name="Other", email="other@test.invalid", password_hash="unused", role="CUSTOMER", status="ACTIVE")
    database.add(other)
    database.flush()
    response = client.post(f"/api/v1/payments/{payment.id}/refresh", headers=_authorization(database, other))
    assert response.status_code == 404
    provider.get_deposit_status.assert_not_called()
    assert client.post(f"/api/v1/payments/{payment.id}/refresh").status_code == 401


@pytest.mark.parametrize("outcome,expected", [("SUBMITTED", "PENDING"), ("FAILED", "FAILED")])
def test_refresh_preserves_provider_outcome(client, database, monkeypatch, outcome, expected):
    customer, _, payment, provider = setup_payment(database, monkeypatch)
    provider.get_deposit_status.return_value["status"] = outcome
    response = client.post(f"/api/v1/payments/{payment.id}/refresh", headers=_authorization(database, customer))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == expected


@pytest.mark.parametrize("failure", ["amount", "currency", "unavailable"])
def test_refresh_never_confirms_unverified_payment(client, database, monkeypatch, failure):
    customer, _, payment, provider = setup_payment(database, monkeypatch)
    if failure == "unavailable":
        provider.get_deposit_status.side_effect = RuntimeError("offline")
    else:
        provider.get_deposit_status.return_value[failure] = "1" if failure == "amount" else "USD"
    response = client.post(f"/api/v1/payments/{payment.id}/refresh", headers=_authorization(database, customer))
    assert response.status_code == (502 if failure == "unavailable" else 422)
    database.refresh(payment)
    assert payment.status == "PENDING"
    assert database.scalar(select(func.count()).select_from(PaymentEvent)) == 0


def test_generic_pawapay_webhook_cannot_invent_success(client, database, monkeypatch):
    _, _, payment, provider = setup_payment(database, monkeypatch)
    provider.get_deposit_status.return_value["status"] = "SUBMITTED"
    result = client.post("/api/v1/payments/webhooks/PAWAPAY", headers={"X-Webhook-Signature": "untrusted"}, json={"provider_reference": payment.provider_reference, "provider_event_id": "invented", "amount_ugx": payment.amount_ugx, "currency": "UGX", "status": "SUCCESSFUL"})
    assert result.status_code == 200
    database.refresh(payment)
    assert payment.status == "PENDING"


def test_reopening_order_recovers_pending_payment(client, database, monkeypatch):
    customer, order, payment, provider = setup_payment(database, monkeypatch)
    result = client.post(f"/api/v1/payments/orders/{order.id}/refresh", headers=_authorization(database, customer))
    assert result.status_code == 200, result.text
    assert result.json()["payment_status"] == "PAID"
    database.refresh(payment)
    assert payment.status == "SUCCESSFUL"


def test_order_refresh_is_private(client, database, monkeypatch):
    _, order, _, provider = setup_payment(database, monkeypatch)
    other = User(name="Other", email="other@test.invalid", password_hash="unused", role="CUSTOMER", status="ACTIVE")
    database.add(other)
    database.flush()
    result = client.post(f"/api/v1/payments/orders/{order.id}/refresh", headers=_authorization(database, other))
    assert result.status_code == 404
    provider.get_deposit_status.assert_not_called()
