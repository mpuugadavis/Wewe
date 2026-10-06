from datetime import timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.models import (
    Campus,
    DeliveryAgent,
    DeliveryAgentLocation,
    DeliveryAssignment,
    DeliveryPoint,
    Order,
    Retailer,
    RetailerFulfillment,
    University,
    User,
    utcnow,
)


def _register_customer(client: TestClient, name: str):
    email = f"{uuid4().hex}@example.test"
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": name,
            "email": email,
            "phone": f"+2567{str(uuid4().int)[:8]}",
            "password": "strong-password-42",
            "role": "CUSTOMER",
        },
    )
    assert response.status_code == 201
    user = response.json()
    login = client.post(
        "/api/v1/auth/login",
        json={"identifier": email, "password": "strong-password-42"},
    )
    assert login.status_code == 200
    return user, {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tracking_fixture(database, client: TestClient):
    customer, customer_headers = _register_customer(client, "Tracking Customer")
    other_customer, other_headers = _register_customer(client, "Other Customer")
    retailer_user = User(
        id=uuid4(),
        name="Tracking Retailer",
        email=f"{uuid4().hex}@example.test",
        password_hash="test-hash",
        role="RETAILER",
        status="ACTIVE",
    )
    rider_user = User(
        id=uuid4(),
        name="Tracking Rider",
        email=f"{uuid4().hex}@example.test",
        password_hash="test-hash",
        role="DELIVERY_AGENT",
        status="ACTIVE",
    )
    database.add_all([retailer_user, rider_user])
    database.flush()

    university = University(
        id=uuid4(),
        name=f"Tracking University {uuid4()}",
        slug=f"tracking-university-{uuid4()}",
    )
    database.add(university)
    database.flush()
    campus = Campus(
        id=uuid4(),
        university_id=university.id,
        name=f"Tracking Campus {uuid4()}",
        slug=f"tracking-campus-{uuid4()}",
    )
    database.add(campus)
    database.flush()

    pickup = DeliveryPoint(
        id=uuid4(),
        campus_id=campus.id,
        kind="BUILDING",
        name="Retailer Pickup",
        directions="Pickup desk",
        latitude=0.3476,
        longitude=32.5825,
        is_active=True,
    )
    dropoff = DeliveryPoint(
        id=uuid4(),
        campus_id=campus.id,
        kind="ROOM",
        name="Customer Dropoff",
        directions="Room 12",
        latitude=0.3500,
        longitude=32.5800,
        is_active=True,
    )
    database.add_all([pickup, dropoff])
    database.flush()

    retailer = Retailer(
        id=uuid4(),
        user_id=retailer_user.id,
        business_name="Tracking Retailer",
        slug=f"tracking-retailer-{uuid4()}",
        phone="+256700000001",
        location_id=pickup.id,
        verification_status="VERIFIED",
        status="ACTIVE",
    )
    database.add(retailer)
    database.flush()

    order = Order(
        id=uuid4(),
        order_number=f"W{uuid4().hex[:12].upper()}",
        customer_id=UUID(customer["id"]),
        delivery_point_id=dropoff.id,
        delivery_method="DELIVERY",
        currency="UGX",
        subtotal_ugx=10000,
        delivery_fee_ugx=1000,
        gross_delivery_fee_ugx=1000,
        multi_retailer_discount_ugx=0,
        multi_retailer_discount_percent=0,
        total_ugx=11000,
        status="OUT_FOR_DELIVERY",
        payment_status="PAID",
    )
    database.add(order)
    database.flush()

    fulfillment = RetailerFulfillment(
        id=uuid4(),
        order_id=order.id,
        retailer_id=retailer.id,
        status="OUT_FOR_DELIVERY",
    )
    database.add(fulfillment)
    database.flush()

    assignment = DeliveryAssignment(
        id=uuid4(),
        fulfillment_id=fulfillment.id,
        agent_id=rider_user.id,
        pickup_point_id=pickup.id,
        dropoff_point_id=dropoff.id,
        status="OUT_FOR_DELIVERY",
        assigned_at=utcnow() - timedelta(minutes=5),
        accepted_at=utcnow() - timedelta(minutes=4),
        picked_up_at=utcnow() - timedelta(minutes=2),
    )
    database.add(assignment)
    database.add(
        DeliveryAgent(
            user_id=rider_user.id,
            phone="+256700000002",
            verification_status="VERIFIED",
            availability_status="BUSY",
            transport_mode="Bicycle",
        )
    )
    database.add(
        DeliveryAgentLocation(
            agent_id=rider_user.id,
            latitude=0.3485,
            longitude=32.5815,
            accuracy_m=8,
            heading_deg=90,
            speed_mps=4.5,
        )
    )
    database.commit()
    return order, rider_user, customer_headers, other_headers, assignment


def test_customer_can_track_assigned_rider_location(client: TestClient, database):
    order, rider, headers, _other_headers, assignment = _tracking_fixture(database, client)

    response = client.get(f"/api/v1/orders/{order.id}/tracking", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == str(order.id)
    assert body["deliveries"][0]["assignment_id"] == str(assignment.id)
    assert body["deliveries"][0]["status"] == "OUT_FOR_DELIVERY"
    assert body["deliveries"][0]["rider"]["name"] == "Tracking Rider"
    assert body["deliveries"][0]["rider"]["transport_mode"] == "Bicycle"
    assert body["deliveries"][0]["location_status"] == "LIVE"
    assert body["deliveries"][0]["location"]["latitude"] == 0.3485
    assert body["deliveries"][0]["location"]["longitude"] == 32.5815
    assert "phone" not in body["deliveries"][0]["rider"]


def test_customer_tracking_is_private(client: TestClient, database):
    order, _rider, _headers, other_headers, _assignment = _tracking_fixture(database, client)

    response = client.get(f"/api/v1/orders/{order.id}/tracking", headers=other_headers)

    assert response.status_code == 404


def test_stale_rider_location_is_not_exposed(client: TestClient, database):
    order, rider, headers, _other_headers, _assignment = _tracking_fixture(database, client)
    location = database.get(DeliveryAgentLocation, rider.id)
    location.updated_at = utcnow() - timedelta(seconds=61)
    database.commit()

    response = client.get(f"/api/v1/orders/{order.id}/tracking", headers=headers)

    assert response.status_code == 200
    delivery = response.json()["deliveries"][0]
    assert delivery["location_status"] == "STALE"
    assert delivery["location"] is None
