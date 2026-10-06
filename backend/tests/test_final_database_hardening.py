"""Database-level tests for Phase 1D order invariants."""
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Campus,
    DeliveryPoint,
    Order,
    OrderItem,
    PickupPoint,
    University,
    User,
)


def _create_order_references(database: Session) -> tuple[User, DeliveryPoint, PickupPoint]:
    customer = User(
        name="Order Integrity Customer",
        phone="+256700000081",
        password_hash="test-hash",
        role="CUSTOMER",
        status="ACTIVE",
    )
    university = University(name="Order Integrity University", slug="order-integrity-university", country_code="UG")
    database.add_all([customer, university])
    database.flush()
    campus = Campus(university_id=university.id, name="Order Integrity Campus", slug="order-integrity-campus")
    database.add(campus)
    database.flush()
    point = DeliveryPoint(campus_id=campus.id, kind="BUILDING", name="Order Integrity Point", is_private=False)
    database.add(point)
    database.flush()
    pickup_point = PickupPoint(delivery_point_id=point.id, operating_status="OPEN")
    database.add(pickup_point)
    database.flush()
    return customer, point, pickup_point


def _order(
    customer: User,
    delivery_method: str,
    delivery_point_id: UUID | None = None,
    pickup_point_id: UUID | None = None,
    *,
    subtotal_ugx: int = 1000,
    delivery_fee_ugx: int = 0,
    total_ugx: int = 1000,
) -> Order:
    return Order(
        order_number=f"WW-{uuid4().hex[:10].upper()}",
        customer_id=customer.id,
        delivery_method=delivery_method,
        delivery_point_id=delivery_point_id,
        pickup_point_id=pickup_point_id,
        currency="UGX",
        subtotal_ugx=subtotal_ugx,
        delivery_fee_ugx=delivery_fee_ugx,
        gross_delivery_fee_ugx=\2,
        multi_retailer_discount_ugx=0,
        multi_retailer_discount_percent=0,
        total_ugx=total_ugx,
        status="PENDING",
        payment_status="UNPAID",
    )


def test_order_destination_must_match_delivery_method(database: Session) -> None:
    customer, point, pickup = _create_order_references(database)
    database.add_all(
        [
            _order(customer, "DELIVERY", delivery_point_id=point.id, total_ugx=1250, delivery_fee_ugx=250),
        gross_delivery_fee_ugx=\2,
        multi_retailer_discount_ugx=0,
        multi_retailer_discount_percent=0,
            _order(customer, "PICKUP", pickup_point_id=pickup.delivery_point_id),
        ]
    )
    database.flush()

    invalid_orders = (
        _order(customer, "DELIVERY"),
        _order(customer, "PICKUP"),
        _order(customer, "DELIVERY", delivery_point_id=point.id, pickup_point_id=pickup.delivery_point_id),
        _order(customer, "PICKUP", delivery_point_id=point.id, pickup_point_id=pickup.delivery_point_id),
    )
    for order in invalid_orders:
        with pytest.raises(IntegrityError):
            with database.begin_nested():
                database.add(order)
                database.flush()


def test_order_total_must_equal_subtotal_plus_delivery_fee(database: Session) -> None:
    customer, point, _pickup = _create_order_references(database)
    database.add(_order(customer, "DELIVERY", delivery_point_id=point.id, subtotal_ugx=1000, delivery_fee_ugx=250,
        gross_delivery_fee_ugx=\2,
        multi_retailer_discount_ugx=0,
        multi_retailer_discount_percent=0, total_ugx=1250))
    database.flush()

    with pytest.raises(IntegrityError):
        with database.begin_nested():
            database.add(
                _order(
                    customer,
                    "DELIVERY",
                    delivery_point_id=point.id,
                    subtotal_ugx=1000,
                    delivery_fee_ugx=250,
        gross_delivery_fee_ugx=250,
        gross_delivery_fee_ugx=\2,
        multi_retailer_discount_ugx=0,
        multi_retailer_discount_percent=0,
        multi_retailer_discount_ugx=0,
        multi_retailer_discount_percent=0,
                    total_ugx=1000,
                )
            )
            database.flush()


def test_order_item_total_must_match_price_and_quantity(database: Session) -> None:
    customer, point, _pickup = _create_order_references(database)
    order = _order(customer, "DELIVERY", delivery_point_id=point.id)
    database.add(order)
    database.flush()

    valid_item = OrderItem(
        order_id=order.id,
        product_name="Order integrity item",
        unit_price_ugx=500,
        quantity=2,
        line_total_ugx=1000,
    )
    database.add(valid_item)
    database.flush()

    with pytest.raises(IntegrityError):
        with database.begin_nested():
            database.add(
                OrderItem(
                    order_id=order.id,
                    product_name="Invalid order integrity item",
                    unit_price_ugx=500,
                    quantity=2,
                    line_total_ugx=999,
                )
            )
            database.flush()


def test_pickup_point_status_accepts_all_api_values(database: Session) -> None:
    _customer, _point, pickup = _create_order_references(database)

    for value in ("OPEN", "CLOSED", "TEMPORARILY_UNAVAILABLE"):
        pickup.operating_status = value
        database.flush()

    with pytest.raises(IntegrityError):
        with database.begin_nested():
            pickup.operating_status = "INVALID"
            database.flush()
    database.refresh(pickup)
    assert pickup.operating_status == "TEMPORARILY_UNAVAILABLE"
