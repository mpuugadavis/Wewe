import secrets

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select

from app.models import (
    Cart,
    CartItem,
    Campus,
    Category,
    CustomerProfile,
    DeliveryAgent,
    DeliveryAssignment,
    DeliveryEarning,
    DeliveryPoint,
    Inventory,
    NotificationOutbox,
    Order,
    OrderItem,
    Payment,
    PaymentEvent,
    PaymentReconciliation,
    PaymentRefund,
    Product,
    RefreshTokenFamily,
    Retailer,
    RetailerFulfillment,
    RetailerProduct,
    University,
    User,
)
from app.routers.commerce import _adjust_order_after_rejection, _release_fulfillment_inventory
from app.schemas import CheckoutIn
from app.security import create_access_token, hash_password
from app.services.orders import create_order, recompute_order_status
from app.services.payment_attempts import (
    record_reconciliation_attempt,
    request_reconciliation,
    reserve_refund_attempt,
    resolve_payment_reconciliation,
    resolve_refund_attempt,
)
from app.services.payments import PaymentInitiation, payment_providers


def _authorization(database, user: User) -> dict[str, str]:
    family = RefreshTokenFamily(user_id=user.id, token_version=user.token_version)
    database.add(family)
    database.flush()
    token = create_access_token(user.id, user.token_version, family.id)
    return {"Authorization": f"Bearer {token}"}


def marketplace_fixture(session):
    university = University(name="Test University", slug="test-university", country_code="UG")
    session.add(university)
    session.flush()
    campus = Campus(university_id=university.id, name="Main", slug="main")
    session.add(campus)
    session.flush()
    customer = User(name="Customer", email="customer@test.invalid", phone="+256700000001", password_hash=hash_password("strong-test-password-42"), role="CUSTOMER", status="ACTIVE")
    owner = User(name="Shop owner", email="shop@test.invalid", phone="+256700000002", password_hash=hash_password("strong-test-password-42"), role="RETAILER", status="ACTIVE")
    session.add_all([customer, owner])
    session.flush()
    point = DeliveryPoint(
        campus_id=campus.id,
        owner_user_id=customer.id,
        kind="ROOM",
        name="Room 1",
        is_private=True,
        latitude="0.327400",
        longitude="32.579500",
    )
    retailer_pickup = DeliveryPoint(
        campus_id=campus.id,
        kind="PICKUP_POINT",
        name="Test Books pickup",
        directions="Test retailer pickup",
        is_private=False,
        latitude="0.335300",
        longitude="32.571300",
    )
    category = Category(name="Books", slug="books")
    session.add_all([point, retailer_pickup, category])
    session.flush()
    session.add(CustomerProfile(user_id=customer.id, preferred_delivery_point_id=point.id))
    retailer = Retailer(
        user_id=owner.id,
        business_name="Test Books",
        slug="test-books",
        phone=owner.phone,
        location_id=retailer_pickup.id,
        verification_status="VERIFIED",
        status="ACTIVE",
    )
    session.add(retailer)
    session.flush()
    product = Product(category_id=category.id, name="Notebook", description="Test product", status="ACTIVE")
    session.add(product)
    session.flush()
    listing = RetailerProduct(retailer_id=retailer.id, product_id=product.id, price_ugx=12000, is_active=True)
    session.add(listing)
    session.flush()
    inventory = Inventory(product_id=product.id, retailer_id=retailer.id, retailer_product_id=listing.id, owner_type="RETAILER", quantity=2, reserved_quantity=0)
    cart = Cart(customer_id=customer.id)
    session.add_all([inventory, cart])
    session.flush()
    session.add(CartItem(cart_id=cart.id, retailer_product_id=listing.id, quantity=2))
    session.commit()
    return customer, point, listing, inventory


def test_checkout_reserves_stock_and_snapshots_price(database) -> None:
    customer, point, listing, inventory = marketplace_fixture(database)
    order = create_order(database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "test-key-0001")
    database.commit()
    database.refresh(inventory)
    line = database.scalar(select(OrderItem).where(OrderItem.order_id == order.id))
    assert order.total_ugx == 27_500
    assert inventory.reserved_quantity == 2
    assert line.unit_price_ugx == 12_000

    listing.price_ugx = 19_000
    database.commit()
    assert database.get(OrderItem, line.id).unit_price_ugx == 12_000


def test_customer_cannot_create_cash_payment_for_open_order(client, database) -> None:
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database,
        customer,
        CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id),
        "cash-payment-key",
    )
    database.commit()

    response = client.post(
        f"/api/v1/orders/{order.id}/payments",
        headers=_authorization(database, customer),
        json={"method": "CASH"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    database.refresh(order)
    assert order.payment_status == "UNPAID"


def test_checkout_rejects_overselling(database) -> None:
    customer, point, listing, inventory = marketplace_fixture(database)
    create_order(database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "test-key-0001")
    database.commit()
    cart = database.scalar(select(Cart).where(Cart.customer_id == customer.id))
    database.add(CartItem(cart_id=cart.id, retailer_product_id=listing.id, quantity=1))
    database.commit()
    with pytest.raises(HTTPException) as error:
        create_order(database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "test-key-0002")
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "insufficient_stock"


def test_private_delivery_point_cannot_be_used_by_another_customer(database) -> None:
    customer, point, listing, _ = marketplace_fixture(database)
    other_customer = User(name="Other customer", email="other@test.invalid", phone="+256700000009", password_hash=hash_password("strong-test-password-42"), role="CUSTOMER", status="ACTIVE")
    database.add(other_customer)
    database.flush()
    other_cart = Cart(customer_id=other_customer.id)
    database.add(other_cart)
    database.flush()
    database.add(CartItem(cart_id=other_cart.id, retailer_product_id=listing.id, quantity=1))
    database.commit()
    with pytest.raises(HTTPException) as error:
        create_order(database, other_customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "private-point-key")
    assert error.value.status_code == 404


def test_multiretailer_order_can_finish_partially(database) -> None:
    customer, point, _, _ = marketplace_fixture(database)
    order = create_order(database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "partial-key-0001")
    first = database.scalar(select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id))
    first.status = "REJECTED"
    second_owner = User(name="Second shop", email="second-shop@test.invalid", phone="+256700000008", password_hash=hash_password("strong-test-password-42"), role="RETAILER", status="ACTIVE")
    database.add(second_owner)
    database.flush()
    second_retailer = Retailer(user_id=second_owner.id, business_name="Second Shop", slug="second-shop", phone=second_owner.phone, verification_status="VERIFIED", status="ACTIVE")
    database.add(second_retailer)
    database.flush()
    database.add(RetailerFulfillment(order_id=order.id, retailer_id=second_retailer.id, status="DELIVERED"))
    database.flush()
    recompute_order_status(database, order)
    database.commit()
    assert order.status == "PARTIALLY_DELIVERED"


def test_releasing_rejected_fulfillment_does_not_release_another_orders_stock(
    client, database
) -> None:
    customer, point, listing, inventory = marketplace_fixture(database)
    cart = database.scalar(select(Cart).where(Cart.customer_id == customer.id))
    cart_item = database.scalar(select(CartItem).where(CartItem.cart_id == cart.id))
    cart_item.quantity = 1
    database.commit()

    rejected_order = create_order(
        database,
        customer,
        CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id),
        "rejected-order-key",
    )
    database.commit()
    rejected_fulfillment = database.scalar(
        select(RetailerFulfillment).where(RetailerFulfillment.order_id == rejected_order.id)
    )

    other_customer = User(
        name="Other customer",
        email="reservation-owner@test.invalid",
        phone="+256700000019",
        password_hash=hash_password("strong-test-password-42"),
        role="CUSTOMER",
        status="ACTIVE",
    )
    database.add(other_customer)
    database.flush()
    public_point = DeliveryPoint(
        campus_id=point.campus_id,
        kind="BUILDING",
        name="Public delivery point",
        is_private=False,
    )
    other_cart = Cart(customer_id=other_customer.id)
    database.add_all([public_point, other_cart])
    database.flush()
    database.add(CartItem(cart_id=other_cart.id, retailer_product_id=listing.id, quantity=1))
    database.commit()

    create_order(
        database,
        other_customer,
        CheckoutIn(delivery_method="DELIVERY", delivery_point_id=public_point.id),
        "other-order-key",
    )
    database.commit()
    assert inventory.reserved_quantity == 2

    _release_fulfillment_inventory(database, rejected_fulfillment.id)
    rejected_fulfillment.status = "REJECTED"
    rejected_order.status = "PARTIALLY_REJECTED"
    database.commit()
    assert inventory.reserved_quantity == 1

    response = client.post(
        f"/api/v1/orders/{rejected_order.id}/cancel",
        headers=_authorization(database, customer),
    )

    assert response.status_code == 200
    assert inventory.reserved_quantity == 1


def test_rejecting_multiple_retailers_removes_one_delivery_fee_each_time(database) -> None:
    customer, point, listing, _inventory = marketplace_fixture(database)
    first_retailer = database.get(Retailer, listing.retailer_id)
    retailers = [first_retailer]
    listings = [listing]
    for index in (2, 3):
        owner = User(
            name=f"Shop owner {index}",
            email=f"shop-owner-{index}@test.invalid",
            phone=f"+25670000010{index}",
            password_hash=hash_password("strong-test-password-42"),
            role="RETAILER",
            status="ACTIVE",
        )
        database.add(owner)
        database.flush()
        retailer = Retailer(
            user_id=owner.id,
            business_name=f"Shop {index}",
            slug=f"shop-{index}",
            phone=owner.phone,
            verification_status="VERIFIED",
            status="ACTIVE",
        )
        database.add(retailer)
        database.flush()
        retailer_listing = RetailerProduct(
            retailer_id=retailer.id,
            product_id=listing.product_id,
            price_ugx=100,
            is_active=True,
        )
        database.add(retailer_listing)
        database.flush()
        retailers.append(retailer)
        listings.append(retailer_listing)

    order = Order(
        order_number="WW-PHASE2FEE",
        customer_id=customer.id,
        delivery_point_id=point.id,
        delivery_method="DELIVERY",
        currency="UGX",
        subtotal_ugx=300,
        delivery_fee_ugx=10_500,
        gross_delivery_fee_ugx=10_500,
        multi_retailer_discount_ugx=0,
        multi_retailer_discount_percent=0,
        total_ugx=10_800,
        status="PENDING",
    )
    database.add(order)
    database.flush()
    fulfillments = []
    for retailer, retailer_listing in zip(retailers, listings):
        fulfillment = RetailerFulfillment(order_id=order.id, retailer_id=retailer.id, status="PENDING")
        database.add(fulfillment)
        database.add(
            OrderItem(
                order_id=order.id,
                product_id=listing.product_id,
                retailer_product_id=retailer_listing.id,
                retailer_id=retailer.id,
                product_name="Notebook",
                unit_price_ugx=100,
                quantity=1,
                line_total_ugx=100,
            )
        )
        fulfillments.append(fulfillment)
    database.commit()

    _adjust_order_after_rejection(database, order, fulfillments[0])
    fulfillments[0].status = "REJECTED"
    database.commit()
    assert order.delivery_fee_ugx == 7_000

    _adjust_order_after_rejection(database, order, fulfillments[1])
    fulfillments[1].status = "REJECTED"
    database.commit()
    assert order.delivery_fee_ugx == 3_500
    assert order.total_ugx == 3_600


def test_rejecting_fulfillment_releases_reservation_and_cancels_delivery(client, database) -> None:
    customer, point, _listing, inventory = marketplace_fixture(database)
    retailer_user = database.scalar(select(User).where(User.role == "RETAILER"))
    order = create_order(
        database,
        customer,
        CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id),
        "reject-fulfillment",
    )
    database.commit()
    fulfillment = database.scalar(
        select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id)
    )
    assignment = database.scalar(
        select(DeliveryAssignment).where(DeliveryAssignment.fulfillment_id == fulfillment.id)
    )

    response = client.post(
        f"/api/v1/retailers/me/fulfillments/{fulfillment.id}/reject",
        json={"reason": "Out of stock"},
        headers=_authorization(database, retailer_user),
    )

    assert response.status_code == 200
    assert database.get(RetailerFulfillment, fulfillment.id).status == "REJECTED"
    assert database.get(DeliveryAssignment, assignment.id).status == "CANCELLED"
    assert inventory.reserved_quantity == 0
    assert database.get(Order, order.id).delivery_fee_ugx == 0


def test_customer_can_cancel_while_mobile_payment_is_pending(client, database) -> None:
    customer, point, _listing, inventory = marketplace_fixture(database)
    order = create_order(
        database,
        customer,
        CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id),
        "pending-payment-cancel",
    )
    database.add(
        Payment(
            order_id=order.id,
            customer_id=customer.id,
            amount_ugx=order.total_ugx,
            currency="UGX",
            method="MTN_MOMO",
            provider="MTN_MOMO",
            provider_reference="phase2-pending-payment",
            status="PENDING",
        )
    )
    order.payment_status = "PENDING"
    database.commit()
    response = client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers=_authorization(database, customer),
    )

    assert response.status_code == 200
    assert database.get(Order, order.id).status == "CANCELLED"
    assert database.get(Order, order.id).payment_status == "PENDING"
    assert inventory.reserved_quantity == 0


def test_legacy_cash_payment_rows_are_not_created_by_checkout(client, database) -> None:
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database,
        customer,
        CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id),
        "pending-cash-cancel",
    )
    database.commit()

    response = client.post(
        f"/api/v1/orders/{order.id}/payments",
        headers=_authorization(database, customer),
        json={"method": "CASH"},
    )

    assert response.status_code == 422
    assert database.scalar(select(Payment.id).where(Payment.order_id == order.id)) is None


def test_admin_cannot_cancel_order_with_pending_mobile_payment(client, database) -> None:
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database,
        customer,
        CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id),
        "admin-pending-payment-cancel",
    )
    database.add(
        Payment(
            order_id=order.id,
            customer_id=customer.id,
            amount_ugx=order.total_ugx,
            currency="UGX",
            method="AIRTEL_MONEY",
            provider="AIRTEL_MONEY",
            provider_reference="phase2-admin-pending-payment",
            status="PENDING",
        )
    )
    order.payment_status = "PENDING"
    admin = User(
        name="Administrator",
        email="payment-admin@test.invalid",
        phone="+256700000056",
        password_hash=hash_password("strong-campus-password-42"),
        role="ADMIN",
        status="ACTIVE",
    )
    database.add(admin)
    database.flush()
    headers = _authorization(database, admin)
    database.commit()

    response = client.patch(
        f"/api/v1/admin/orders/{order.id}/status",
        json={"status": "CANCELLED", "reason": "Customer request"},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "payment_resolution_required"
    assert database.get(Order, order.id).status == "PENDING"


def test_pending_payment_cannot_receive_refund_webhook(client, database, monkeypatch) -> None:
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database,
        customer,
        CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id),
        "pending-refund-webhook",
    )
    payment = Payment(
        order_id=order.id,
        customer_id=customer.id,
        amount_ugx=order.total_ugx,
        currency="UGX",
        method="MTN_MOMO",
        provider="MTN_MOMO",
        provider_reference="phase2-refund-reference",
        status="PENDING",
    )
    database.add(payment)
    order.payment_status = "PENDING"
    database.commit()

    class Provider:
        def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
            return True

    monkeypatch.setattr(payment_providers, "get", lambda _method: Provider())
    response = client.post(
        "/api/v1/payments/webhooks/MTN_MOMO",
        headers={"X-Webhook-Signature": "valid"},
        json={
            "provider_reference": payment.provider_reference,
            "provider_event_id": "refund-before-success",
            "amount_ugx": payment.amount_ugx,
            "currency": "UGX",
            "status": "REFUNDED",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "payment_not_refundable"
    assert database.get(Payment, payment.id).status == "PENDING"
    assert database.scalar(select(PaymentEvent.id)) is None


def _webhook_adapter(monkeypatch) -> None:
    class Provider:
        def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
            return True

    monkeypatch.setattr(payment_providers, "get", lambda _method: Provider())


def _create_payment_for_order(database, order, customer, status: str = "PENDING") -> Payment:
    payment = Payment(
        order_id=order.id,
        customer_id=customer.id,
        amount_ugx=order.total_ugx,
        currency="UGX",
        method="MTN_MOMO",
        provider="MTN_MOMO",
        provider_reference="pending-reference",
        status=status,
    )
    payment.provider_reference = f"contract-{order.id}-{secrets.token_hex(8)}"
    database.add(payment)
    order.payment_status = {
        "PENDING": "PENDING",
        "SUCCESSFUL": "PAID",
        "FAILED": "FAILED",
        "REFUNDED": "REFUNDED",
    }[status]
    database.commit()
    return payment


def _send_payment_event(client, payment, status: str, event_id: str):
    return client.post(
        "/api/v1/payments/webhooks/MTN_MOMO",
        headers={"X-Webhook-Signature": "valid"},
        json={
            "provider_reference": payment.provider_reference or payment.attempt_reference,
            "provider_event_id": event_id,
            "amount_ugx": payment.amount_ugx,
            "currency": "UGX",
            "status": status,
        },
    )


def _register_payment_initiator(monkeypatch, error: Exception | None = None) -> list:
    initiated = []

    class Provider:
        name = "MTN_MOMO"

        def initiate(self, request):
            initiated.append(request)
            if error:
                raise error
            return PaymentInitiation(provider_reference=f"provider-{request.reference}")

        def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
            return True

    monkeypatch.setattr(payment_providers, "get", lambda _method: Provider())
    return initiated


def _start_payment(client, database, order, customer, key: str, method: str = "MTN_MOMO"):
    return client.post(
        f"/api/v1/orders/{order.id}/payments",
        headers={**_authorization(database, customer), "Idempotency-Key": key},
        json={"method": method, "phone": "+256700000001"},
    )


def test_payment_pending_can_transition_to_successful_or_failed(client, database, monkeypatch) -> None:
    _webhook_adapter(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    successful_order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "state-success"
    )
    successful_payment = _create_payment_for_order(database, successful_order, customer)
    failed_payment = _create_payment_for_order(database, successful_order, customer)

    success_response = _send_payment_event(client, successful_payment, "SUCCESSFUL", "success-event")
    failure_response = _send_payment_event(client, failed_payment, "FAILED", "failure-event")

    assert success_response.status_code == 200
    assert failure_response.status_code == 200
    assert database.get(Payment, successful_payment.id).status == "SUCCESSFUL"
    assert database.get(Payment, failed_payment.id).status == "FAILED"


@pytest.mark.parametrize(
    ("initial_status", "event_status"),
    [("SUCCESSFUL", "FAILED"), ("FAILED", "SUCCESSFUL")],
)
def test_conflicting_final_payment_transitions_are_rejected(
    client, database, monkeypatch, initial_status: str, event_status: str
) -> None:
    _webhook_adapter(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), f"conflict-{initial_status}"
    )
    payment = _create_payment_for_order(database, order, customer, initial_status)

    response = _send_payment_event(client, payment, event_status, f"conflict-event-{initial_status}")

    assert response.status_code == 409
    assert database.get(Payment, payment.id).status == initial_status


def test_successful_payment_can_transition_to_refunded_via_callback(client, database, monkeypatch) -> None:
    _webhook_adapter(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "success-refund"
    )
    payment = _create_payment_for_order(database, order, customer, "SUCCESSFUL")

    response = _send_payment_event(client, payment, "REFUNDED", "successful-refund-event")

    assert response.status_code == 200
    assert database.get(Payment, payment.id).status == "REFUNDED"
    assert database.get(Order, order.id).payment_status == "REFUNDED"


def test_duplicate_payment_event_is_idempotent(client, database, monkeypatch) -> None:
    _webhook_adapter(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "duplicate-event"
    )
    payment = _create_payment_for_order(database, order, customer)

    first = _send_payment_event(client, payment, "SUCCESSFUL", "duplicate-success-event")
    notifications_after_first = database.scalar(
        select(func.count(NotificationOutbox.id)).where(NotificationOutbox.event_type == "PAYMENT_SUCCESSFUL")
    )
    second = _send_payment_event(client, payment, "SUCCESSFUL", "duplicate-success-event")
    notifications_after_second = database.scalar(
        select(func.count(NotificationOutbox.id)).where(NotificationOutbox.event_type == "PAYMENT_SUCCESSFUL")
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert notifications_after_first == notifications_after_second == 1


def test_conflicting_payment_event_does_not_overwrite_terminal_status(client, database, monkeypatch) -> None:
    _webhook_adapter(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "conflicting-events"
    )
    payment = _create_payment_for_order(database, order, customer)

    successful = _send_payment_event(client, payment, "SUCCESSFUL", "success-before-failure")
    conflicting = _send_payment_event(client, payment, "FAILED", "late-failure")

    assert successful.status_code == 200
    assert conflicting.status_code == 409
    assert database.get(Payment, payment.id).status == "SUCCESSFUL"
    event = database.scalar(select(PaymentEvent).where(PaymentEvent.provider_event_id == "MTN_MOMO:late-failure"))
    assert event.status == "FAILED"
    assert event.disposition == "CONFLICT"
    assert database.scalar(
        select(PaymentReconciliation.id).where(
            PaymentReconciliation.payment_id == payment.id,
            PaymentReconciliation.state == "CONFLICT",
        )
    )


def test_pending_payment_blocks_an_immediate_second_attempt(client, database) -> None:
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "pending-retry"
    )
    _create_payment_for_order(database, order, customer)

    response = client.post(
        f"/api/v1/orders/{order.id}/payments",
        headers=_authorization(database, customer),
        json={"method": "MTN_MOMO", "phone": "+256700000001"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "payment_pending"


def test_provider_initiation_timeout_remains_unresolved_and_blocks_retry(client, database, monkeypatch) -> None:
    _register_payment_initiator(monkeypatch, TimeoutError("Provider response was not received"))
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "uncertain-initiation"
    )
    database.commit()
    headers = _authorization(database, customer)

    initiation = client.post(
        f"/api/v1/orders/{order.id}/payments",
        headers=headers,
        json={"method": "MTN_MOMO", "phone": "+256700000001"},
    )
    payment = database.scalar(select(Payment).where(Payment.order_id == order.id))
    retry = client.post(
        f"/api/v1/orders/{order.id}/payments",
        headers=headers,
        json={"method": "MTN_MOMO", "phone": "+256700000001"},
    )

    assert initiation.status_code == 502
    assert payment.status == "UNKNOWN"
    assert payment.attempt_reference
    assert payment.initiated_at is not None
    assert payment.resolved_at is None
    assert database.get(Order, order.id).payment_status == "PENDING"
    assert database.scalar(
        select(PaymentReconciliation.id).where(
            PaymentReconciliation.payment_id == payment.id,
            PaymentReconciliation.state == "UNRESOLVED",
        )
    )
    assert retry.status_code == 409


def test_late_success_after_cancellation_does_not_reopen_order(client, database, monkeypatch) -> None:
    _webhook_adapter(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "late-success-cancelled"
    )
    payment = _create_payment_for_order(database, order, customer)
    order.status = "CANCELLED"
    database.commit()

    response = _send_payment_event(client, payment, "SUCCESSFUL", "late-success-event")

    assert response.status_code == 200
    assert database.get(Payment, payment.id).status == "SUCCESSFUL"
    assert database.get(Order, order.id).status == "CANCELLED"
    assert database.get(Order, order.id).payment_status == "PAID"


def test_refunding_one_capture_does_not_mark_order_refunded_while_another_succeeded(
    client, database, monkeypatch
) -> None:
    _webhook_adapter(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "multiple-captures"
    )
    first_payment = _create_payment_for_order(database, order, customer)
    second_payment = _create_payment_for_order(database, order, customer)
    first_capture = _send_payment_event(client, first_payment, "SUCCESSFUL", "first-capture")
    first_duplicate = _send_payment_event(client, first_payment, "SUCCESSFUL", "first-capture")
    second_capture = _send_payment_event(client, second_payment, "SUCCESSFUL", "second-capture")
    second_duplicate = _send_payment_event(client, second_payment, "SUCCESSFUL", "second-capture")
    response = _send_payment_event(client, first_payment, "REFUNDED", "one-of-two-refunded")

    assert first_capture.status_code == second_capture.status_code == 200
    assert first_duplicate.json()["duplicate"] is True
    assert second_duplicate.json()["duplicate"] is True
    assert response.status_code == 200
    assert database.get(Payment, first_payment.id).status == "REFUNDED"
    assert database.get(Payment, second_payment.id).status == "SUCCESSFUL"
    assert database.get(Order, order.id).payment_status == "PAID"
    assert database.scalar(select(func.count(PaymentEvent.id)).where(PaymentEvent.status == "SUCCESSFUL")) == 2
    refund = database.scalar(select(PaymentRefund).where(PaymentRefund.payment_id == first_payment.id))
    assert refund.amount_ugx == first_payment.amount_ugx
    assert refund.status == "CONFIRMED"


def _add_delivery_agent(database, suffix: str) -> User:
    user = User(
        name="Delivery Agent",
        email=f"delivery-agent-{suffix}@test.invalid",
        phone=f"+2567000000{suffix[-2:]}",
        password_hash=hash_password("strong-campus-password-42"),
        role="DELIVERY_AGENT",
        status="ACTIVE",
    )
    database.add(user)
    database.flush()
    database.add(
        DeliveryAgent(
            user_id=user.id,
            phone=user.phone,
            verification_status="VERIFIED",
            availability_status="AVAILABLE",
        )
    )
    database.commit()
    return user


def test_pickup_is_distinct_from_acceptance_and_duplicate_delivery_is_rejected(client, database) -> None:
    customer, point, _listing, inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "delivery-state-contract"
    )
    fulfillment = database.scalar(select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id))
    assignment = database.scalar(select(DeliveryAssignment).where(DeliveryAssignment.fulfillment_id == fulfillment.id))
    agent_user = _add_delivery_agent(database, "64")
    fulfillment.status = "READY"
    order.status = "READY"
    assignment.agent_id = agent_user.id
    assignment.status = "ACCEPTED"
    assignment.confirmation_code_hash = None
    database.commit()
    customer_delivery_fee = order.delivery_fee_ugx
    headers = _authorization(database, agent_user)

    invalid_direct_delivery = client.post(
        f"/api/v1/deliveries/{assignment.id}/status",
        headers=headers,
        json={"status": "DELIVERED"},
    )
    picked_up = client.post(
        f"/api/v1/deliveries/{assignment.id}/status",
        headers=headers,
        json={"status": "PICKED_UP"},
    )
    duplicate_pickup = client.post(
        f"/api/v1/deliveries/{assignment.id}/status",
        headers=headers,
        json={"status": "PICKED_UP"},
    )
    out_for_delivery = client.post(
        f"/api/v1/deliveries/{assignment.id}/status",
        headers=headers,
        json={"status": "OUT_FOR_DELIVERY"},
    )
    delivered = client.post(
        f"/api/v1/deliveries/{assignment.id}/status",
        headers=headers,
        json={"status": "DELIVERED"},
    )
    duplicate_delivery = client.post(
        f"/api/v1/deliveries/{assignment.id}/status",
        headers=headers,
        json={"status": "DELIVERED"},
    )

    assert invalid_direct_delivery.status_code == 409
    assert picked_up.status_code == 200
    assert database.get(DeliveryAssignment, assignment.id).picked_up_at is not None
    assert duplicate_pickup.status_code == 409
    assert out_for_delivery.status_code == 200
    assert delivered.status_code == 200
    assert duplicate_delivery.status_code == 409
    assert inventory.quantity == 0
    assert inventory.reserved_quantity == 0
    assert database.get(Order, order.id).delivery_fee_ugx == customer_delivery_fee
    assert database.scalar(select(func.count(DeliveryEarning.assignment_id))) == 1


def test_cancelled_delivery_assignment_cannot_complete_delivery(client, database) -> None:
    customer, point, _listing, inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "cancelled-delivery-state"
    )
    fulfillment = database.scalar(select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id))
    assignment = database.scalar(select(DeliveryAssignment).where(DeliveryAssignment.fulfillment_id == fulfillment.id))
    agent_user = _add_delivery_agent(database, "65")
    fulfillment.status = "CANCELLED"
    assignment.agent_id = agent_user.id
    assignment.status = "CANCELLED"
    assignment.confirmation_code_hash = None
    inventory.reserved_quantity = 0
    database.commit()

    response = client.post(
        f"/api/v1/deliveries/{assignment.id}/status",
        headers=_authorization(database, agent_user),
        json={"status": "DELIVERED"},
    )

    assert response.status_code == 409
    assert database.get(DeliveryAssignment, assignment.id).status == "CANCELLED"
    assert inventory.quantity == 2


@pytest.mark.parametrize(
    ("fulfillment_status", "order_status"),
    [
        ("PENDING", "PENDING"),
        ("CONFIRMED", "CONFIRMED"),
        ("PREPARING", "PREPARING"),
        ("READY", "READY"),
    ],
)
def test_customer_can_cancel_fulfillment_before_pickup(
    client, database, fulfillment_status: str, order_status: str
) -> None:
    customer, point, _listing, inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), f"cancel-{fulfillment_status}"
    )
    fulfillment = database.scalar(select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id))
    fulfillment.status = fulfillment_status
    order.status = order_status
    database.commit()

    response = client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers=_authorization(database, customer),
    )

    assert response.status_code == 200
    assert database.get(RetailerFulfillment, fulfillment.id).status == "CANCELLED"
    assert inventory.reserved_quantity == 0
    assert inventory.quantity == 2


def test_agent_acceptance_does_not_block_customer_cancellation(client, database) -> None:
    customer, point, _listing, inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "cancel-after-accept"
    )
    fulfillment = database.scalar(select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id))
    assignment = database.scalar(select(DeliveryAssignment).where(DeliveryAssignment.fulfillment_id == fulfillment.id))
    fulfillment.status = "READY"
    order.status = "READY"
    agent_user = User(
        name="Available Agent",
        email="cancel-accepted-agent@test.invalid",
        phone="+256700000061",
        password_hash=hash_password("strong-campus-password-42"),
        role="DELIVERY_AGENT",
        status="ACTIVE",
    )
    database.add(agent_user)
    database.flush()
    database.add(
        DeliveryAgent(
            user_id=agent_user.id,
            phone=agent_user.phone,
            verification_status="VERIFIED",
            availability_status="AVAILABLE",
        )
    )
    database.commit()
    accepted = client.post(
        f"/api/v1/deliveries/{assignment.id}/accept",
        headers=_authorization(database, agent_user),
    )
    assert accepted.status_code == 200
    assert database.get(DeliveryAssignment, assignment.id).status == "ACCEPTED"
    assert database.get(DeliveryAssignment, assignment.id).picked_up_at is None

    cancelled = client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers=_authorization(database, customer),
    )
    assert cancelled.status_code == 200
    assert inventory.reserved_quantity == 0


@pytest.mark.parametrize(
    ("fulfillment_status", "assignment_status", "order_status"),
    [
        ("READY", "PICKED_UP", "READY"),
        ("OUT_FOR_DELIVERY", "OUT_FOR_DELIVERY", "OUT_FOR_DELIVERY"),
        ("DELIVERED", "DELIVERED", "DELIVERED"),
        ("CANCELLED", "CANCELLED", "CANCELLED"),
    ],
)
def test_customer_cancellation_is_blocked_after_pickup_or_terminal_state(
    client, database, fulfillment_status: str, assignment_status: str, order_status: str
) -> None:
    customer, point, _listing, inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), f"cancel-block-{assignment_status}"
    )
    fulfillment = database.scalar(select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id))
    assignment = database.scalar(select(DeliveryAssignment).where(DeliveryAssignment.fulfillment_id == fulfillment.id))
    fulfillment.status = fulfillment_status
    assignment.status = assignment_status
    if assignment_status in {"PICKED_UP", "OUT_FOR_DELIVERY", "DELIVERED"}:
        assignment.picked_up_at = order.created_at
    order.status = order_status
    database.commit()

    response = client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers=_authorization(database, customer),
    )

    assert response.status_code == 409
    assert inventory.reserved_quantity == 2


def test_paid_order_cancellation_creates_idempotent_refund_request(client, database) -> None:
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database,
        customer,
        CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id),
        "cancel-paid-refund",
    )
    payment = _create_payment_for_order(database, order, customer, "SUCCESSFUL")
    order.payment_status = "PAID"
    database.commit()

    response = client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers=_authorization(database, customer),
    )

    assert response.status_code == 200
    assert database.get(Order, order.id).status == "CANCELLED"
    assert database.get(Payment, payment.id).status == "SUCCESSFUL"
    refund = database.scalar(select(PaymentRefund).where(PaymentRefund.payment_id == payment.id))
    assert refund is not None
    assert refund.amount_ugx == payment.amount_ugx
    assert refund.status == "SUBMITTED"
    assert refund.idempotency_key == f"order-cancellation:{order.id}:payment:{payment.id}"
    payload = response.json()
    assert payload["payment_status"] == "PAID"
    assert payload["refunds"][0]["status"] == "SUBMITTED"


def test_cancellation_repeated_request_does_not_release_reservation_twice(client, database) -> None:
    customer, point, _listing, inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "cancel-idempotence"
    )
    database.commit()
    headers = _authorization(database, customer)

    first = client.post(f"/api/v1/orders/{order.id}/cancel", headers=headers)
    second = client.post(f"/api/v1/orders/{order.id}/cancel", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 409
    assert inventory.reserved_quantity == 0
    assert inventory.quantity == 2


def test_rejected_fulfillment_reservation_release_is_one_time(client, database) -> None:
    customer, point, _listing, inventory = marketplace_fixture(database)
    retailer_user = database.scalar(select(User).where(User.role == "RETAILER"))
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "reject-once"
    )
    fulfillment = database.scalar(select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id))
    headers = _authorization(database, retailer_user)

    first = client.post(
        f"/api/v1/retailers/me/fulfillments/{fulfillment.id}/reject",
        json={"reason": "Unavailable"},
        headers=headers,
    )
    second = client.post(
        f"/api/v1/retailers/me/fulfillments/{fulfillment.id}/reject",
        json={"reason": "Repeated request"},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert inventory.reserved_quantity == 0
    assert inventory.quantity == 2
    assert database.get(RetailerFulfillment, fulfillment.id).status == "REJECTED"
    assert database.scalar(select(func.count(DeliveryEarning.assignment_id))) == 0


def test_rejecting_one_retailer_fulfillment_preserves_other_retailer_reservation(client, database) -> None:
    customer, point, listing, inventory = marketplace_fixture(database)
    original_owner = database.scalar(select(User).where(User.role == "RETAILER"))
    second_owner = User(
        name="Other shop owner",
        email="other-shop@test.invalid",
        phone="+256700000066",
        password_hash=hash_password("strong-campus-password-42"),
        role="RETAILER",
        status="ACTIVE",
    )
    database.add(second_owner)
    database.flush()
    second_pickup = DeliveryPoint(
        campus_id=point.campus_id,
        name="Other Shop pickup",
        kind="PICKUP_POINT",
        latitude=0.335300,
        longitude=32.571300,
        is_active=True,
    )
    database.add(second_pickup)
    database.flush()
    second_retailer = Retailer(
        user_id=second_owner.id,
        business_name="Other Shop",
        slug="other-shop",
        phone=second_owner.phone,
        verification_status="VERIFIED",
        status="ACTIVE",
        location_id=second_pickup.id,
    )
    database.add(second_retailer)
    database.flush()
    product = Product(
        category_id=database.get(Product, listing.product_id).category_id,
        name="Other notebook",
        description="Other retailer item",
        status="ACTIVE",
    )
    database.add(product)
    database.flush()
    second_listing = RetailerProduct(
        retailer_id=second_retailer.id,
        product_id=product.id,
        price_ugx=5000,
        is_active=True,
    )
    database.add(second_listing)
    database.flush()
    second_inventory = Inventory(
        product_id=product.id,
        retailer_id=second_retailer.id,
        retailer_product_id=second_listing.id,
        owner_type="RETAILER",
        quantity=3,
        reserved_quantity=0,
    )
    cart = database.scalar(select(Cart).where(Cart.customer_id == customer.id))
    database.add_all(
        [
            second_inventory,
            CartItem(cart_id=cart.id, retailer_product_id=second_listing.id, quantity=1),
        ]
    )
    database.commit()
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "two-retailer-reject"
    )
    rejected_fulfillment = database.scalar(
        select(RetailerFulfillment).where(
            RetailerFulfillment.order_id == order.id,
            RetailerFulfillment.retailer_id == listing.retailer_id,
        )
    )

    response = client.post(
        f"/api/v1/retailers/me/fulfillments/{rejected_fulfillment.id}/reject",
        json={"reason": "Unavailable"},
        headers=_authorization(database, original_owner),
    )

    assert response.status_code == 200
    assert inventory.reserved_quantity == 0
    assert second_inventory.reserved_quantity == 1
    assert inventory.quantity == 2
    assert second_inventory.quantity == 3
    assert database.scalar(select(func.count(DeliveryEarning.assignment_id))) == 0


def test_successfully_paid_order_can_be_cancelled_before_pickup(client, database) -> None:
    customer, point, _listing, inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "paid-order-cancel"
    )
    payment = _create_payment_for_order(database, order, customer, "SUCCESSFUL")

    response = client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers=_authorization(database, customer),
    )

    assert response.status_code == 200
    assert database.get(Order, order.id).status == "CANCELLED"
    assert database.get(Payment, payment.id).status == "SUCCESSFUL"
    assert inventory.reserved_quantity == 0


def test_recompute_all_cancelled_fulfillments_uses_existing_cancelled_order_state(database) -> None:
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "all-cancelled-state"
    )
    fulfillment = database.scalar(select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id))
    fulfillment.status = "CANCELLED"
    order.status = "CANCELLED"

    recompute_order_status(database, order)

    assert order.status == "CANCELLED"


def test_recompute_mixed_delivered_cancelled_fulfillments_does_not_fall_back_to_pending(database) -> None:
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "mixed-cancel-state"
    )
    fulfillment = database.scalar(select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id))
    fulfillment.status = "CANCELLED"
    second_owner = User(
        name="Second retailer owner",
        email="mixed-cancel-retailer@test.invalid",
        phone="+256700000062",
        password_hash=hash_password("strong-campus-password-42"),
        role="RETAILER",
        status="ACTIVE",
    )
    database.add(second_owner)
    database.flush()
    second_retailer = Retailer(
        user_id=second_owner.id,
        business_name="Second retailer",
        slug="mixed-cancel-retailer",
        phone=second_owner.phone,
        verification_status="VERIFIED",
        status="ACTIVE",
    )
    database.add(second_retailer)
    database.flush()
    database.add(RetailerFulfillment(order_id=order.id, retailer_id=second_retailer.id, status="DELIVERED"))
    order.status = "OUT_FOR_DELIVERY"
    database.flush()

    recompute_order_status(database, order)

    assert order.status != "PENDING"
    assert order.status == "OUT_FOR_DELIVERY"


def test_refund_transition_never_refunds_more_than_captured_full_payment(client, database, monkeypatch) -> None:
    _webhook_adapter(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "refund-capture-cap"
    )
    payment = _create_payment_for_order(database, order, customer, "SUCCESSFUL")
    admin = User(
        name="Refund Admin",
        email="refund-cap-admin@test.invalid",
        phone="+256700000063",
        password_hash=hash_password("strong-campus-password-42"),
        role="ADMIN",
        status="ACTIVE",
    )
    database.add(admin)
    database.flush()
    admin_headers = _authorization(database, admin)
    database.commit()

    response = client.post(
        f"/api/v1/admin/payments/{payment.id}/confirm-refund",
        headers=admin_headers,
        json={"provider_event_id": "refund-cap-reference"},
    )
    duplicate = client.post(
        f"/api/v1/admin/payments/{payment.id}/confirm-refund",
        headers=admin_headers,
        json={"provider_event_id": "refund-cap-reference"},
    )

    assert response.status_code == 200
    assert response.json()["amount_ugx"] == payment.amount_ugx
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert database.scalar(
        select(func.count(PaymentEvent.id)).where(PaymentEvent.provider_event_id == "admin-refund:refund-cap-reference")
    ) == 1
    assert database.get(Payment, payment.id).status == "REFUNDED"


def test_same_payment_idempotency_key_reuses_attempt_without_second_charge(client, database, monkeypatch) -> None:
    initiated = _register_payment_initiator(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "idempotent-attempt"
    )
    database.commit()

    first = _start_payment(client, database, order, customer, "same-key-001")
    second = _start_payment(client, database, order, customer, "same-key-001")

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["idempotent_replay"] is True
    assert len(initiated) == 1
    assert database.scalar(select(func.count(Payment.id)).where(Payment.order_id == order.id)) == 1


def test_payment_idempotency_key_rejects_changed_amount(client, database, monkeypatch) -> None:
    _register_payment_initiator(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "key-changed-amount"
    )
    database.commit()
    first = _start_payment(client, database, order, customer, "changed-amount-key")
    order.delivery_fee_ugx += 1000
    order.total_ugx += 1000
    database.commit()

    conflict = _start_payment(client, database, order, customer, "changed-amount-key")

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_key_conflict"
    assert database.scalar(select(func.count(Payment.id)).where(Payment.order_id == order.id)) == 1


def test_payment_idempotency_key_rejects_different_order(client, database, monkeypatch) -> None:
    _register_payment_initiator(monkeypatch)
    customer, point, listing, _inventory = marketplace_fixture(database)
    first_order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "key-first-order"
    )
    database.commit()
    first = _start_payment(client, database, first_order, customer, "cross-order-key")
    cart = database.scalar(select(Cart).where(Cart.customer_id == customer.id))
    inventory = database.scalar(select(Inventory).where(Inventory.retailer_product_id == listing.id))
    inventory.quantity = 5
    database.add(CartItem(cart_id=cart.id, retailer_product_id=listing.id, quantity=1))
    database.commit()
    second_order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "key-second-order"
    )
    database.commit()

    conflict = _start_payment(client, database, second_order, customer, "cross-order-key")

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_key_conflict"
    assert database.scalar(select(func.count(Payment.id)).where(Payment.idempotency_key == "cross-order-key")) == 1


def test_payment_idempotency_key_rejects_different_method(client, database, monkeypatch) -> None:
    _register_payment_initiator(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "key-method"
    )
    database.commit()

    first = _start_payment(client, database, order, customer, "method-context-key", "MTN_MOMO")
    conflict = _start_payment(client, database, order, customer, "method-context-key", "AIRTEL_MONEY")

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_key_conflict"


def test_authoritative_reconciliation_failure_allows_new_attempt(client, database, monkeypatch) -> None:
    initiated = _register_payment_initiator(monkeypatch, TimeoutError("ambiguous initiation"))
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "reconcile-failure"
    )
    database.commit()
    first = _start_payment(client, database, order, customer, "uncertain-first-key")
    payment = database.scalar(select(Payment).where(Payment.order_id == order.id))
    requested = request_reconciliation(database, payment.id, reason="provider initiation response uncertain")
    attempted = record_reconciliation_attempt(database, payment.id, evidence={"attempt": 1})
    resolved = resolve_payment_reconciliation(
        database,
        payment.id,
        outcome="FAILED",
        evidence={"source": "verified-authoritative-result"},
        authoritative=True,
        provider_reference="provider-failed-reference",
    )
    database.commit()
    initiated_error = initiated[0]

    monkeypatch.setattr(payment_providers, "get", lambda method: _SuccessfulTestProvider(method))
    retry = _start_payment(client, database, order, customer, "uncertain-retry-key")

    assert first.status_code == 502
    assert initiated_error.reference == payment.attempt_reference
    assert requested.state == "REQUESTED"
    assert attempted.state == "ATTEMPTED"
    assert resolved.state == "AUTHORITATIVE_FAILURE"
    assert database.get(Payment, payment.id).status == "FAILED"
    assert retry.status_code == 201
    assert database.scalar(select(func.count(Payment.id)).where(Payment.order_id == order.id)) == 2


def test_duplicate_failed_provider_event_is_idempotent(client, database, monkeypatch) -> None:
    _webhook_adapter(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "duplicate-failed-event"
    )
    payment = _create_payment_for_order(database, order, customer)

    first = _send_payment_event(client, payment, "FAILED", "duplicate-failure-event")
    second = _send_payment_event(client, payment, "FAILED", "duplicate-failure-event")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert database.get(Payment, payment.id).status == "FAILED"
    assert database.scalar(
        select(func.count(PaymentEvent.id)).where(PaymentEvent.provider_event_id == "MTN_MOMO:duplicate-failure-event")
    ) == 1


def test_cancelled_uncertain_order_accepts_late_success_without_reopening(client, database, monkeypatch) -> None:
    _register_payment_initiator(monkeypatch, TimeoutError("initiation outcome unknown"))
    customer, point, _listing, inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "late-success-uncertain"
    )
    database.commit()
    started = _start_payment(client, database, order, customer, "late-success-key")
    payment = database.scalar(select(Payment).where(Payment.order_id == order.id))
    cancelled = client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers=_authorization(database, customer),
    )

    late_success = _send_payment_event(client, payment, "SUCCESSFUL", "late-uncertain-success")

    assert started.status_code == 502
    assert cancelled.status_code == 200
    assert late_success.status_code == 200
    assert database.get(Payment, payment.id).status == "SUCCESSFUL"
    assert database.get(Order, order.id).status == "CANCELLED"
    assert database.get(Order, order.id).payment_status == "PAID"
    assert inventory.reserved_quantity == 0
    assert database.scalar(
        select(PaymentReconciliation.id).where(
            PaymentReconciliation.payment_id == payment.id,
            PaymentReconciliation.state == "MANUAL_REVIEW",
        )
    )
    assert database.scalar(select(func.count(PaymentRefund.id)).where(PaymentRefund.payment_id == payment.id)) == 0


def test_reconciled_success_after_cancellation_records_manual_review(client, database, monkeypatch) -> None:
    _register_payment_initiator(monkeypatch, TimeoutError("initiation outcome unknown"))
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "reconciled-late-success"
    )
    database.commit()
    started = _start_payment(client, database, order, customer, "reconciled-late-success-key")
    payment = database.scalar(select(Payment).where(Payment.order_id == order.id))
    cancelled = client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers=_authorization(database, customer),
    )

    resolution = resolve_payment_reconciliation(
        database,
        payment.id,
        outcome="SUCCESSFUL",
        evidence={"source": "verified-authoritative-result"},
        authoritative=True,
        provider_reference="reconciled-success-reference",
    )
    database.commit()

    assert started.status_code == 502
    assert cancelled.status_code == 200
    assert resolution.state == "AUTHORITATIVE_SUCCESS"
    assert database.get(Payment, payment.id).status == "SUCCESSFUL"
    assert database.get(Order, order.id).status == "CANCELLED"
    assert database.scalar(
        select(PaymentReconciliation.id).where(
            PaymentReconciliation.payment_id == payment.id,
            PaymentReconciliation.state == "MANUAL_REVIEW",
        )
    )


def test_successful_attempt_idempotency_replay_does_not_charge_again(client, database, monkeypatch) -> None:
    initiated = _register_payment_initiator(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "success-replay"
    )
    database.commit()

    first = _start_payment(client, database, order, customer, "success-replay-key")
    payment = database.scalar(select(Payment).where(Payment.order_id == order.id))
    success = _send_payment_event(client, payment, "SUCCESSFUL", "success-replay-event")
    replay = _start_payment(client, database, order, customer, "success-replay-key")

    assert first.status_code == 201
    assert success.status_code == 200
    assert replay.status_code == 201
    assert replay.json()["id"] == str(payment.id)
    assert replay.json()["idempotent_replay"] is True
    assert len(initiated) == 1
    assert database.scalar(select(func.count(Payment.id)).where(Payment.order_id == order.id)) == 1


def test_refunded_attempt_replay_does_not_start_a_new_charge(client, database, monkeypatch) -> None:
    initiated = _register_payment_initiator(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "refunded-replay"
    )
    database.commit()

    first = _start_payment(client, database, order, customer, "refunded-attempt-key")
    payment = database.scalar(select(Payment).where(Payment.order_id == order.id))
    _send_payment_event(client, payment, "SUCCESSFUL", "before-refund-event")
    _send_payment_event(client, payment, "REFUNDED", "after-refund-event")
    replay = _start_payment(client, database, order, customer, "refunded-attempt-key")

    assert replay.status_code == 201
    assert replay.json()["id"] == str(payment.id)
    assert replay.json()["idempotent_replay"] is True
    assert database.get(Payment, payment.id).status == "REFUNDED"
    assert len(initiated) == 1


def test_refund_attempt_cannot_exceed_captured_balance(client, database, monkeypatch) -> None:
    _webhook_adapter(monkeypatch)
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "refund-balance-cap"
    )
    payment = _create_payment_for_order(database, order, customer, "SUCCESSFUL")
    first = reserve_refund_attempt(
        database, payment.id, amount_ugx=payment.amount_ugx - 100, idempotency_key="refund-part-one"
    )
    resolve_refund_attempt(database, first.id, outcome="CONFIRMED", evidence={"confirmed": True})
    database.commit()

    with pytest.raises(HTTPException) as error:
        reserve_refund_attempt(
            database, payment.id, amount_ugx=101, idempotency_key="refund-over-cap"
        )

    assert error.value.status_code == 409
    assert database.get(Payment, payment.id).status == "SUCCESSFUL"


def test_unknown_refund_attempt_reserves_balance_until_resolved(database) -> None:
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database, customer, CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id), "refund-unknown-reserve"
    )
    payment = _create_payment_for_order(database, order, customer, "SUCCESSFUL")
    refund = reserve_refund_attempt(
        database, payment.id, amount_ugx=payment.amount_ugx - 50, idempotency_key="refund-unresolved"
    )
    resolve_refund_attempt(database, refund.id, outcome="UNKNOWN", evidence={"response": "ambiguous"})
    database.commit()

    with pytest.raises(HTTPException) as error:
        reserve_refund_attempt(
            database, payment.id, amount_ugx=51, idempotency_key="refund-over-reserved"
        )

    assert error.value.status_code == 409
    assert database.get(PaymentRefund, refund.id).status == "UNKNOWN"


class _SuccessfulTestProvider:
    def __init__(self, method: str) -> None:
        self.name = method

    def initiate(self, request):
        return PaymentInitiation(provider_reference=f"retry-{request.reference}")

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        return True


def test_agent_cannot_change_phone_during_active_delivery(client, database) -> None:
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database,
        customer,
        CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id),
        "active-agent-phone",
    )
    agent_user = User(
        name="Delivery Agent",
        email="active-agent@test.invalid",
        phone="+256700000052",
        password_hash=hash_password("strong-campus-password-42"),
        role="DELIVERY_AGENT",
        status="ACTIVE",
    )
    database.add(agent_user)
    database.flush()
    agent = DeliveryAgent(
        user_id=agent_user.id,
        phone=agent_user.phone,
        verification_status="VERIFIED",
        availability_status="BUSY",
    )
    database.add(agent)
    fulfillment = database.scalar(
        select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id)
    )
    database.flush()
    assignment = database.scalar(
        select(DeliveryAssignment).where(DeliveryAssignment.fulfillment_id == fulfillment.id)
    )
    assignment.agent_id = agent_user.id
    assignment.status = "ACCEPTED"
    response = client.patch(
        "/api/v1/deliveries/me/profile",
        json={"phone": "+256700000053"},
        headers=_authorization(database, agent_user),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "active_delivery"
    agent = database.get(DeliveryAgent, agent_user.id)
    assert agent.phone == "+256700000052"
    assert agent.verification_status == "VERIFIED"


def test_delivery_completion_requires_customer_confirmation_code(client, database) -> None:
    customer, point, _listing, inventory = marketplace_fixture(database)
    order = create_order(
        database,
        customer,
        CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id),
        "delivery-confirmation-code",
    )
    fulfillment = database.scalar(
        select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id)
    )
    assignment = database.scalar(
        select(DeliveryAssignment).where(DeliveryAssignment.fulfillment_id == fulfillment.id)
    )
    agent_user = User(
        name="Confirmation Agent",
        email="confirmation-agent@test.invalid",
        phone="+256700000057",
        password_hash=hash_password("strong-campus-password-42"),
        role="DELIVERY_AGENT",
        status="ACTIVE",
    )
    database.add(agent_user)
    database.flush()
    database.add(
        DeliveryAgent(
            user_id=agent_user.id,
            phone=agent_user.phone,
            verification_status="VERIFIED",
            availability_status="BUSY",
        )
    )
    assignment.agent_id = agent_user.id
    assignment.status = "OUT_FOR_DELIVERY"
    fulfillment.status = "OUT_FOR_DELIVERY"
    order.status = "OUT_FOR_DELIVERY"
    notification = database.scalar(
        select(NotificationOutbox).where(
            NotificationOutbox.user_id == customer.id,
            NotificationOutbox.event_type == "ORDER_PLACED",
        )
    )
    confirmation_code = notification.payload["delivery_confirmation_codes"][str(fulfillment.id)]
    wrong_confirmation_code = "00000000" if confirmation_code != "00000000" else "00000001"
    family = RefreshTokenFamily(user_id=agent_user.id, token_version=agent_user.token_version)
    database.add(family)
    database.flush()
    token = create_access_token(agent_user.id, agent_user.token_version, family.id)
    database.commit()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"/api/v1/deliveries/{assignment.id}/status"

    missing_code = client.post(url, json={"status": "DELIVERED"}, headers=headers)
    wrong_code = client.post(
        url,
        json={"status": "DELIVERED", "confirmation_code": wrong_confirmation_code},
        headers=headers,
    )

    assert missing_code.status_code == 403
    assert wrong_code.status_code == 403
    assert database.get(DeliveryAssignment, assignment.id).status == "OUT_FOR_DELIVERY"
    assert inventory.reserved_quantity == 2

    completed = client.post(
        url,
        json={"status": "DELIVERED", "confirmation_code": confirmation_code},
        headers=headers,
    )

    assert completed.status_code == 200
    assert database.get(DeliveryAssignment, assignment.id).status == "DELIVERED"
    assert inventory.quantity == 0
    assert inventory.reserved_quantity == 0


def test_admin_cannot_assign_delivery_to_inactive_agent(client, database) -> None:
    customer, point, _listing, _inventory = marketplace_fixture(database)
    order = create_order(
        database,
        customer,
        CheckoutIn(delivery_method="DELIVERY", delivery_point_id=point.id),
        "inactive-agent-assignment",
    )
    fulfillment = database.scalar(
        select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id)
    )
    fulfillment.status = "READY"
    assignment = database.scalar(
        select(DeliveryAssignment).where(DeliveryAssignment.fulfillment_id == fulfillment.id)
    )
    admin = User(
        name="Administrator",
        email="phase2-admin@test.invalid",
        phone="+256700000054",
        password_hash=hash_password("strong-campus-password-42"),
        role="ADMIN",
        status="ACTIVE",
    )
    agent_user = User(
        name="Inactive Agent",
        email="inactive-agent@test.invalid",
        phone="+256700000055",
        password_hash=hash_password("strong-campus-password-42"),
        role="DELIVERY_AGENT",
        status="SUSPENDED",
    )
    database.add_all([admin, agent_user])
    database.flush()
    database.add(
        DeliveryAgent(
            user_id=agent_user.id,
            phone=agent_user.phone,
            verification_status="VERIFIED",
            availability_status="AVAILABLE",
        )
    )
    headers = _authorization(database, admin)
    database.commit()

    response = client.post(
        f"/api/v1/admin/deliveries/{assignment.id}/assign",
        json={"agent_user_id": str(agent_user.id)},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agent_unavailable"
    assert database.get(DeliveryAssignment, assignment.id).status == "UNASSIGNED"
