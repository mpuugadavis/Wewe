from uuid import uuid4
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app.dependencies import Principal
from app.models import NotificationOutbox, RetailerFulfillment, Order
from app.routers.admin import assign_delivery
from app.routers.operations import accept_delivery, list_notifications, _delivery_view
from app.schemas import AdminDeliveryAssignment
from app.security import hash_token
from app.services.delivery_confirmation import issue_delivery_confirmation
from app.services.delivery_dispatch import accept_offer, advance_dispatch
from app.services.notification_outbox import _email_handler, NotificationChannelUnavailable
from app.services.orders import recompute_order_status
from test_delivery_dispatch import _dispatch_fixture, _user


@pytest.mark.parametrize("route", ["offer", "admin", "direct"])
def test_assignment_sends_matching_customer_only_codes(database, route):
    assignment, rider, _ = _dispatch_fixture(database)
    if route == "offer":
        offer = advance_dispatch(database, assignment.id)
        accept_offer(database, rider.id, offer.id)
    elif route == "admin":
        admin = _user("ADMIN", "Admin")
        database.add(admin)
        database.flush()
        assign_delivery(assignment.id, AdminDeliveryAssignment(agent_user_id=rider.id), principal=Principal(admin, uuid4()), db=database)
    else:
        accept_delivery.__wrapped__(Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": ("127.0.0.1", 1)}), assignment.id, principal=Principal(rider, uuid4()), db=database)
    database.flush()
    rows = database.scalars(select(NotificationOutbox).where(NotificationOutbox.event_type == "DELIVERY_ASSIGNED")).all()
    assert {row.channel for row in rows} == {"EMAIL", "IN_APP"}
    assert len(rows) == 2
    code = rows[0].payload["confirmation_code"]
    assert len(code) == 8 and code.isdigit()
    assert assignment.confirmation_code_hash == hash_token(code)
    for row in rows:
        assert row.payload["confirmation_code"] == code
        assert code in row.payload["message"]
        assert row.payload["assignment_id"] == str(assignment.id)
        assert row.user_id != rider.id
    assert code not in str(_delivery_view(database, assignment, reveal_destination=True))
    assert code not in str(list_notifications(limit=50, principal=Principal(rider, uuid4()), db=database))
    fulfillment = database.get(RetailerFulfillment, assignment.fulfillment_id)
    order = database.get(Order, fulfillment.order_id)
    old_hash = assignment.confirmation_code_hash
    issue_delivery_confirmation(database, assignment, order)
    assert assignment.confirmation_code_hash != old_hash


def test_unconfigured_smtp_does_not_report_email_sent(monkeypatch):
    monkeypatch.setattr("app.services.notification_outbox.get_settings", lambda: SimpleNamespace(smtp_host=None))
    with pytest.raises(NotificationChannelUnavailable):
        _email_handler(NotificationOutbox(payload={"to": "customer@example.test", "subject": "Code", "body": "Test"}))


def test_order_closes_only_after_all_deliveries_finish(database):
    assignment, _, _ = _dispatch_fixture(database)
    fulfillment = database.get(RetailerFulfillment, assignment.fulfillment_id)
    order = database.get(Order, fulfillment.order_id)
    # A second retailer fulfillment is provided by a second independent fixture.
    other, _, _ = _dispatch_fixture(database)
    second = database.get(RetailerFulfillment, other.fulfillment_id)
    second.order_id = order.id
    second.status = "OUT_FOR_DELIVERY"
    fulfillment.status = "DELIVERED"
    database.flush()
    recompute_order_status(database, order)
    assert order.status == "OUT_FOR_DELIVERY"
    second.status = "DELIVERED"
    recompute_order_status(database, order)
    assert order.status == "DELIVERED"
    assert order.delivered_at is not None
    second.status = "CANCELLED"
    recompute_order_status(database, order)
    assert order.status == "PARTIALLY_DELIVERED"


def test_delivery_without_issued_code_cannot_close(database):
    from fastapi import HTTPException
    from app.routers.operations import update_delivery_status
    from app.schemas import DeliveryStatusUpdate
    assignment, rider, _ = _dispatch_fixture(database)
    assignment.agent_id = rider.id
    assignment.status = "OUT_FOR_DELIVERY"
    fulfillment = database.get(RetailerFulfillment, assignment.fulfillment_id)
    fulfillment.status = "OUT_FOR_DELIVERY"
    database.commit()
    with pytest.raises(HTTPException) as error:
        update_delivery_status.__wrapped__(assignment.id, DeliveryStatusUpdate(status="DELIVERED", confirmation_code="12345678"), Request({"type": "http"}), principal=Principal(rider, uuid4()), db=database)
    assert error.value.status_code == 403
    assert assignment.status == "OUT_FOR_DELIVERY"
