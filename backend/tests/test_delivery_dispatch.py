from datetime import timedelta
from uuid import uuid4

from app.models import (
    DeliveryAgent,
    DeliveryAgentLocation,
    DeliveryAssignment,
    DeliveryPoint,
    DeliveryOffer,
    Order,
    Retailer,
    RetailerFulfillment,
    User,
    University,
    Campus,
    utcnow,
)
from app.services.delivery_dispatch import (
    OFFER_TTL_SECONDS,
    accept_offer,
    advance_dispatch,
    haversine_distance_m,
    list_active_offers,
    reject_offer,
)


def _user(role: str, name: str) -> User:
    return User(
        id=uuid4(),
        name=name,
        email=f"{uuid4()}@example.test",
        password_hash="test-hash",
        role=role,
        status="ACTIVE",
    )


def _dispatch_fixture(database):
    customer = _user("CUSTOMER", "Customer")
    retailer_user = _user("RETAILER", "Retailer")
    rider_a = _user("DELIVERY_AGENT", "Rider A")
    rider_b = _user("DELIVERY_AGENT", "Rider B")
    database.add_all([customer, retailer_user, rider_a, rider_b])
    database.flush()

    university = University(id=uuid4(), name=f"Test University {uuid4()}", slug=f"test-university-{uuid4()}")
    database.add(university)
    database.flush()
    campus = Campus(id=uuid4(), university_id=university.id, name=f"Test Campus {uuid4()}", slug=f"test-campus-{uuid4()}")
    database.add(campus)
    database.flush()

    pickup = DeliveryPoint(
        id=uuid4(),
        campus_id=campus.id,
        kind="BUILDING",
        name="Retailer Pickup",
        latitude=0.3476,
        longitude=32.5825,
        is_active=True,
    )
    dropoff = DeliveryPoint(
        id=uuid4(),
        campus_id=campus.id,
        kind="ROOM",
        name="Customer Dropoff",
        latitude=0.3500,
        longitude=32.5800,
        is_active=True,
    )
    database.add_all([pickup, dropoff])
    database.flush()

    retailer = Retailer(
        id=uuid4(),
        user_id=retailer_user.id,
        business_name="Test Retailer",
        slug=f"test-retailer-{uuid4()}",
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
        customer_id=customer.id,
        delivery_point_id=dropoff.id,
        delivery_method="DELIVERY",
        currency="UGX",
        subtotal_ugx=10000,
        delivery_fee_ugx=1000,
        total_ugx=11000,
        status="READY",
        payment_status="PAID",
    )
    database.add(order)
    database.flush()

    fulfillment = RetailerFulfillment(
        id=uuid4(),
        order_id=order.id,
        retailer_id=retailer.id,
        status="READY",
        ready_at=utcnow(),
    )
    database.add(fulfillment)
    database.flush()

    assignment = DeliveryAssignment(
        id=uuid4(),
        fulfillment_id=fulfillment.id,
        status="UNASSIGNED",
        pickup_point_id=pickup.id,
        dropoff_point_id=dropoff.id,
    )
    database.add(assignment)

    for rider, latitude, longitude in (
        (rider_a, 0.3477, 32.5826),
        (rider_b, 0.3550, 32.5900),
    ):
        database.add(
            DeliveryAgent(
                user_id=rider.id,
                phone=f"+2567{str(uuid4().int)[:8]}",
                verification_status="VERIFIED",
                availability_status="AVAILABLE",
                transport_mode="Bicycle",
            )
        )
        database.add(
            DeliveryAgentLocation(
                agent_id=rider.id,
                latitude=latitude,
                longitude=longitude,
                accuracy_m=8,
            )
        )
    database.commit()
    return assignment, rider_a, rider_b


def test_haversine_distance_is_positive():
    assert haversine_distance_m(0.3476, 32.5825, 0.3477, 32.5826) > 0


def test_dispatch_selects_nearest_fresh_verified_available_rider(database):
    assignment, rider_a, rider_b = _dispatch_fixture(database)

    offer = advance_dispatch(database, assignment.id)

    assert offer is not None
    assert offer.agent_id == rider_a.id
    assert offer.status == "PENDING"
    assert offer.expires_at > offer.offered_at
    assert (offer.expires_at - offer.offered_at).total_seconds() == OFFER_TTL_SECONDS


def test_expired_offer_advances_to_next_candidate(database):
    assignment, rider_a, rider_b = _dispatch_fixture(database)

    first = advance_dispatch(database, assignment.id)
    assert first is not None
    first.expires_at = utcnow() - timedelta(seconds=1)
    database.flush()

    second = advance_dispatch(database, assignment.id)

    assert second is not None
    assert second.id != first.id
    assert second.agent_id == rider_b.id
    assert first.status == "EXPIRED"


def test_accepting_offer_assigns_rider_and_cancels_competing_pending_offers(database):
    assignment, rider_a, rider_b = _dispatch_fixture(database)
    first = advance_dispatch(database, assignment.id)
    assert first is not None

    second = DeliveryOffer(
        assignment_id=assignment.id,
        agent_id=rider_b.id,
        status="PENDING",
        offer_sequence=2,
        offered_at=utcnow(),
        expires_at=utcnow() + timedelta(seconds=OFFER_TTL_SECONDS),
        distance_m=1000,
    )
    database.add(second)
    database.commit()

    accepted = accept_offer(database, rider_a.id, first.id)

    assert accepted.id == assignment.id
    assert accepted.agent_id == rider_a.id
    assert accepted.status == "ACCEPTED"
    assert first.status == "ACCEPTED"
    assert second.status == "CANCELLED"


def test_rejecting_offer_advances_dispatch(database):
    assignment, rider_a, rider_b = _dispatch_fixture(database)
    first = advance_dispatch(database, assignment.id)
    assert first is not None

    rejected = reject_offer(database, rider_a.id, first.id)

    assert rejected.status == "REJECTED"
    next_offer = database.scalar(
        __import__("sqlalchemy").select(DeliveryOffer)
        .where(DeliveryOffer.assignment_id == assignment.id, DeliveryOffer.status == "PENDING")
    )
    assert next_offer is not None
    assert next_offer.agent_id in {rider_a.id, rider_b.id}
    assert next_offer.agent_id != first.agent_id


def test_pre_pickup_acceptance_can_be_released_for_redispatch():
    from app.services.state_transitions import is_delivery_assignment_transition_allowed

    assert is_delivery_assignment_transition_allowed("ACCEPTED", "UNASSIGNED")
    assert not is_delivery_assignment_transition_allowed("PICKED_UP", "UNASSIGNED")
    assert not is_delivery_assignment_transition_allowed("OUT_FOR_DELIVERY", "UNASSIGNED")