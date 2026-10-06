"""Database-level coverage for Phase 1C integrity constraints."""
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Campus,
    Category,
    DeliveryAgent,
    DeliveryAssignment,
    DeliveryEarning,
    DeliveryPoint,
    Inventory,
    Order,
    OrderItem,
    Payment,
    PaymentEvent,
    PickupPoint,
    Product,
    Retailer,
    RetailerFulfillment,
    RetailerProduct,
    Review,
    University,
    User,
)


def _create_integrity_fixture(database: Session) -> dict[str, object]:
    university = University(name="Integrity University", slug="integrity-university", country_code="UG")
    database.add(university)
    database.flush()
    campus = Campus(university_id=university.id, name="Integrity Campus", slug="integrity-campus")
    database.add(campus)
    customer = User(
        name="Integrity Customer",
        email="integrity-customer@example.test",
        phone="+256700000091",
        password_hash="test-hash",
        role="CUSTOMER",
        status="ACTIVE",
    )
    retailer_user = User(
        name="Integrity Retailer",
        email="integrity-retailer@example.test",
        phone="+256700000092",
        password_hash="test-hash",
        role="RETAILER",
        status="ACTIVE",
    )
    agent_user = User(
        name="Integrity Agent",
        email="integrity-agent@example.test",
        phone="+256700000093",
        password_hash="test-hash",
        role="DELIVERY_AGENT",
        status="ACTIVE",
    )
    database.add_all([customer, retailer_user, agent_user])
    database.flush()

    delivery_point = DeliveryPoint(
        campus_id=campus.id,
        kind="BUILDING",
        name="Integrity Building",
        is_private=False,
    )
    retailer = Retailer(
        user_id=retailer_user.id,
        business_name="Integrity Shop",
        slug="integrity-shop",
        phone="+256700000092",
        verification_status="PENDING",
        status="ACTIVE",
    )
    agent = DeliveryAgent(
        user_id=agent_user.id,
        phone="+256700000093",
        verification_status="PENDING",
        availability_status="OFFLINE",
    )
    category = Category(name="Integrity Category", slug="integrity-category")
    database.add_all([delivery_point, retailer, agent, category])
    database.flush()

    pickup_point = PickupPoint(delivery_point_id=delivery_point.id, operating_status="OPEN")
    product = Product(category_id=category.id, name="Integrity Product", status="ACTIVE")
    database.add_all([pickup_point, product])
    database.flush()

    listing = RetailerProduct(
        retailer_id=retailer.id,
        product_id=product.id,
        price_ugx=1000,
        is_active=True,
    )
    database.add(listing)
    database.flush()
    inventory = Inventory(
        product_id=product.id,
        retailer_id=retailer.id,
        retailer_product_id=listing.id,
        owner_type="RETAILER",
        quantity=1,
        reserved_quantity=0,
    )
    order = Order(
        order_number="INT-000000000001",
        customer_id=customer.id,
        delivery_point_id=delivery_point.id,
        delivery_method="DELIVERY",
        currency="UGX",
        subtotal_ugx=1000,
        delivery_fee_ugx=0,
        gross_delivery_fee_ugx=\2,
        multi_retailer_discount_ugx=0,
        multi_retailer_discount_percent=0,
        total_ugx=1000,
        status="PENDING",
        payment_status="UNPAID",
    )
    database.add_all([inventory, order])
    database.flush()

    order_item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        retailer_product_id=listing.id,
        retailer_id=retailer.id,
        product_name=product.name,
        unit_price_ugx=1000,
        quantity=1,
        line_total_ugx=1000,
    )
    fulfillment = RetailerFulfillment(
        order_id=order.id,
        retailer_id=retailer.id,
        status="PENDING",
    )
    payment = Payment(
        order_id=order.id,
        customer_id=customer.id,
        amount_ugx=1000,
        currency="UGX",
        method="MTN_MOMO",
        provider="MTN_MOMO",
        status="PENDING",
    )
    database.add_all([order_item, fulfillment, payment])
    database.flush()

    assignment = DeliveryAssignment(
        fulfillment_id=fulfillment.id,
        agent_id=agent.user_id,
        status="UNASSIGNED",
    )
    review = Review(
        product_id=product.id,
        customer_id=customer.id,
        order_item_id=order_item.id,
        rating=5,
        moderation_status="VISIBLE",
    )
    database.add_all([assignment, review])
    database.flush()

    earning = DeliveryEarning(
        assignment_id=assignment.id,
        agent_id=agent.user_id,
        amount_ugx=100,
        currency="UGX",
        status="PENDING",
    )
    payment_event = PaymentEvent(
        payment_id=payment.id,
        provider_event_id="integrity-event-0001",
        status="SUCCESSFUL",
    )
    database.add_all([earning, payment_event])
    database.flush()

    return {
        "retailer": retailer,
        "agent": agent,
        "pickup_point": pickup_point,
        "listing": listing,
        "fulfillment": fulfillment,
        "assignment": assignment,
        "earning": earning,
        "payment_event": payment_event,
        "review": review,
    }


def _assert_status_domain(
    database: Session,
    record: object,
    attribute: str,
    allowed_values: tuple[str, ...],
) -> None:
    for value in allowed_values:
        setattr(record, attribute, value)
        database.flush()

    with pytest.raises(IntegrityError):
        with database.begin_nested():
            setattr(record, attribute, "INVALID_STATUS")
            database.flush()
    database.refresh(record)


def test_retailer_product_price_must_be_nonnegative(database: Session) -> None:
    world = _create_integrity_fixture(database)
    listing = world["listing"]

    listing.price_ugx = 2500
    database.flush()
    listing.price_ugx = 0
    database.flush()

    with pytest.raises(IntegrityError):
        with database.begin_nested():
            listing.price_ugx = -1
            database.flush()
    database.refresh(listing)
    assert listing.price_ugx == 0


@pytest.mark.parametrize("phone", ["", "   ", "\t\n\r\f\v"])
def test_retailer_phone_must_not_be_blank(database: Session, phone: str) -> None:
    world = _create_integrity_fixture(database)
    retailer = world["retailer"]
    retailer.phone = "+256700000092"
    database.flush()

    with pytest.raises(IntegrityError):
        with database.begin_nested():
            retailer.phone = phone
            database.flush()
    database.refresh(retailer)
    assert retailer.phone == "+256700000092"


def test_enum_like_status_columns_reject_values_outside_application_domains(database: Session) -> None:
    world = _create_integrity_fixture(database)
    domains = (
        ("retailer", "status", ("ACTIVE", "INACTIVE")),
        ("agent", "verification_status", ("PENDING", "VERIFIED", "REJECTED")),
        ("agent", "availability_status", ("OFFLINE", "AVAILABLE", "BUSY")),
        (
            "fulfillment",
            "status",
            ("PENDING", "CONFIRMED", "REJECTED", "PREPARING", "READY", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"),
        ),
        ("assignment", "status", ("UNASSIGNED", "ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED")),
        ("earning", "status", ("PENDING", "PAID")),
        ("payment_event", "status", ("SUCCESSFUL", "FAILED", "REFUNDED")),
        ("review", "moderation_status", ("VISIBLE", "HIDDEN")),
    )

    for record_name, attribute, allowed_values in domains:
        _assert_status_domain(database, world[record_name], attribute, allowed_values)
