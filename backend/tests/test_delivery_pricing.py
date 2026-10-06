"""Delivery-pricing tests for the approved Phase 4A COM-FEE rules.

The pricing engine itself is provider-neutral: it prices a road-route distance
that the routing service produced. These tests never contact a real routing
provider (``conftest.FakeRoutingProvider`` is installed for every test) and
never assert that a straight-line distance is a road distance.

``TEST_CONFIG`` values are deliberately small, clearly-labelled test fixtures.
They are NOT approved WEWE production prices. The approved production
configuration lives in ``APPROVED_DELIVERY_PRICING_CONFIG`` and is taken from
``docs/WEWE_COMMERCE_BUSINESS_RULES_PHASE_4A.md`` (COM-FEE-001/COM-FEE-008).
"""

from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import select

from app.models import (
    Cart,
    CartItem,
    Campus,
    Category,
    CustomerProfile,
    DeliveryPoint,
    Order,
    DeliveryQuote,
    Inventory,
    PickupPoint,
    PlatformSetting,
    Product,
    RefreshTokenFamily,
    Retailer,
    RetailerFulfillment,
    RetailerProduct,
    University,
    User,
)
from app.schemas import CheckoutIn
from app.security import create_access_token, hash_password
from app.services.delivery_pricing import (
    APPROVED_DELIVERY_PRICING_CONFIG,
    DELIVERY,
    PICKUP,
    PRICING_SETTING_KEY,
    DeliveryPricingConfig,
    DeliveryPricingError,
    build_delivery_quote,
    remove_committed_delivery_quote,
    resolve_delivery_pricing_config,
    total_delivery_fee,
)
from app.services.routing import GeoCoordinate, RoutingProviderError
from app.services.orders import create_order
from app.services.payments import PaymentInitiation, payment_providers
from app.routers.commerce import _adjust_order_after_rejection

PASSWORD = "delivery-pricing-password-42"


def configure_routes(fixture: dict, fake_routing, distances) -> None:
    """Price each retailer leg with the given road-route distance (in km)."""

    destination = fixture["destination_coordinate"]
    for coordinate, distance_km in zip(fixture["retailer_coordinates"], distances):
        fake_routing.set_route(coordinate, destination, distance_km)

#: Test-only pricing fixture (base 1000, 500 per km, minimum 2000, 500 increment).
TEST_CONFIG = DeliveryPricingConfig(
    base_fee_ugx=1000,
    price_per_km_ugx=Decimal("500"),
    minimum_fee_ugx=2000,
    rounding_increment_ugx=500,
    max_route_distance_km=Decimal("50"),
)


def _authorization(database, user: User) -> dict[str, str]:
    family = RefreshTokenFamily(user_id=user.id, token_version=user.token_version)
    database.add(family)
    database.flush()
    token = create_access_token(user.id, user.token_version, family.id)
    return {"Authorization": f"Bearer {token}"}


def _retailer_with_listing(database, campus_id, index: int, price_ugx: int = 10_000):
    owner = User(
        name=f"Pricing retailer {index}",
        email=f"pricing-retailer-{index}-{uuid4().hex[:8]}@test.invalid",
        phone=f"+2567{uuid4().hex[:8]}",
        password_hash=hash_password(PASSWORD),
        role="RETAILER",
        status="ACTIVE",
    )
    database.add(owner)
    database.flush()
    retailer = Retailer(
        user_id=owner.id,
        business_name=f"Pricing shop {index}",
        slug=f"pricing-shop-{index}-{uuid4().hex[:8]}",
        phone=owner.phone,
        verification_status="VERIFIED",
        status="ACTIVE",
    )
    database.add(retailer)
    database.flush()
    product = Product(category_id=_category_id(database), name=f"Priced item {index}", status="ACTIVE")
    database.add(product)
    database.flush()
    listing = RetailerProduct(retailer_id=retailer.id, product_id=product.id, price_ugx=price_ugx, is_active=True)
    database.add(listing)
    database.flush()
    inventory = Inventory(
        product_id=product.id,
        retailer_id=retailer.id,
        retailer_product_id=listing.id,
        owner_type="RETAILER",
        quantity=10,
        reserved_quantity=0,
    )
    database.add(inventory)
    database.flush()
    return retailer, listing


def _category_id(database) -> object:
    category = database.scalar(select(Category))
    if category is None:
        category = Category(name="Pricing category", slug=f"pricing-{uuid4().hex[:8]}")
        database.add(category)
        database.flush()
    return category.id


def pricing_fixture(session, retailer_count: int = 2) -> dict:
    university = University(name=f"Pricing University {uuid4().hex[:6]}", slug=f"pricing-university-{uuid4().hex[:8]}", country_code="UG")
    session.add(university)
    session.flush()
    campus = Campus(university_id=university.id, name="Main", slug=f"main-{uuid4().hex[:8]}")
    session.add(campus)
    session.flush()
    customer = User(
        name="Pricing customer",
        email=f"pricing-customer-{uuid4().hex[:8]}@test.invalid",
        phone=f"+2567{uuid4().hex[:8]}",
        password_hash=hash_password(PASSWORD),
        role="CUSTOMER",
        status="ACTIVE",
    )
    session.add(customer)
    session.flush()
    # Known coordinates so a test can ask the routing double for an exact route.
    destination_coordinate = GeoCoordinate(Decimal("0.331700"), Decimal("32.574400"))
    point = DeliveryPoint(
        campus_id=campus.id,
        owner_user_id=customer.id,
        kind="ROOM",
        name="Pricing room",
        directions="Livingstone Hall, Block A",
        latitude=destination_coordinate.latitude,
        longitude=destination_coordinate.longitude,
        is_private=True,
    )
    pickup_location = DeliveryPoint(campus_id=campus.id, kind="PICKUP_POINT", name="Pricing pickup location", is_private=False)
    session.add_all([point, pickup_location])
    session.flush()
    pickup_point = PickupPoint(delivery_point_id=pickup_location.id, operating_status="OPEN")
    session.add_all([CustomerProfile(user_id=customer.id, preferred_delivery_point_id=point.id), pickup_point])
    session.flush()
    cart = Cart(customer_id=customer.id)
    session.add(cart)
    session.flush()
    retailers = []
    listings = []
    retailer_coordinates = []
    for index in range(1, retailer_count + 1):
        retailer, listing = _retailer_with_listing(session, campus.id, index)
        # Each retailer gets its own pickup location so each fulfillment leg is
        # routed (and therefore priced) independently.
        origin_coordinate = GeoCoordinate(
            Decimal("0.330000") + Decimal(index) * Decimal("0.002000"),
            Decimal("32.570000"),
        )
        origin = DeliveryPoint(
            campus_id=campus.id,
            kind="BUILDING",
            name=f"Pricing shop {index}",
            latitude=origin_coordinate.latitude,
            longitude=origin_coordinate.longitude,
            is_private=False,
        )
        session.add(origin)
        session.flush()
        retailer.location_id = origin.id
        retailers.append(retailer)
        listings.append(listing)
        retailer_coordinates.append(origin_coordinate)
        session.add(CartItem(cart_id=cart.id, retailer_product_id=listing.id, quantity=1))
    session.commit()
    return {
        "customer": customer,
        "point": point,
        "destination_coordinate": destination_coordinate,
        "retailer_coordinates": retailer_coordinates,
        "pickup_point": pickup_point,
        "retailers": retailers,
        "listings": listings,
    }

def test_pickup_quote_is_zero_and_carries_no_route_distance() -> None:
    quote = build_delivery_quote(
        APPROVED_DELIVERY_PRICING_CONFIG,
        retailer_id=uuid4(),
        mode=PICKUP,
    )

    assert quote.delivery_fee_ugx == 0
    assert quote.mode == PICKUP
    assert quote.route_distance_km is None
    assert quote.currency == "UGX"


def test_pickup_quote_rejects_a_route_distance() -> None:
    with pytest.raises(DeliveryPricingError) as error:
        build_delivery_quote(
            APPROVED_DELIVERY_PRICING_CONFIG,
            retailer_id=uuid4(),
            mode=PICKUP,
            route_distance_km=Decimal("3"),
        )

    assert error.value.code == "unexpected_route_distance"


def test_delivery_quote_requires_a_route_distance() -> None:
    with pytest.raises(DeliveryPricingError) as error:
        build_delivery_quote(
            APPROVED_DELIVERY_PRICING_CONFIG,
            retailer_id=uuid4(),
            mode=DELIVERY,
        )

    assert error.value.code == "route_distance_required"


def test_minimum_fee_is_respected() -> None:
    # 0.5 km with the test fixture gives 1000 + 250 = 1250, below the 2000 minimum.
    assert TEST_CONFIG.delivery_fee(Decimal("0.5")) == 2000
    # 1 km with the approved configuration gives 2000, below the UGX 2,500 minimum.
    assert APPROVED_DELIVERY_PRICING_CONFIG.delivery_fee(Decimal("1")) == 2500


def test_distance_pricing_follows_the_approved_formula() -> None:
    config = APPROVED_DELIVERY_PRICING_CONFIG

    # Documented Phase 4A examples.
    assert config.delivery_fee(Decimal("5")) == 4000
    assert config.delivery_fee(Decimal("2")) == 2500
    assert config.delivery_fee(Decimal("8")) == 5500
    # Alternative test fixture only.
    assert TEST_CONFIG.delivery_fee(Decimal("5")) == 3500


def test_muhika_scale_distances_produce_distance_dependent_fees() -> None:
    config = APPROVED_DELIVERY_PRICING_CONFIG

    # This guards the real checkout symptom: a 2.7 km route must not price
    # the same as an 8.1 km route. The approved UGX 500 increment is retained,
    # so the expected values are 2.9 -> 3.0k and 5.55 -> 5.5k.
    assert config.delivery_fee(Decimal("2.7")) == 3000
    assert config.delivery_fee(Decimal("8.1")) == 5500
    assert config.delivery_fee(Decimal("2.7")) < config.delivery_fee(Decimal("8.1"))


def test_longer_distance_never_costs_less() -> None:
    fees = [
        APPROVED_DELIVERY_PRICING_CONFIG.delivery_fee(Decimal(distance))
        for distance in ("1", "3", "5", "10", "15")
    ]

    assert fees == sorted(fees)
    assert fees[-1] > fees[0]


def test_zero_distance_uses_the_base_fee_then_the_minimum() -> None:
    assert APPROVED_DELIVERY_PRICING_CONFIG.delivery_fee(Decimal("0")) == 2500
    assert TEST_CONFIG.delivery_fee(Decimal("0")) == 2000
    assert TEST_CONFIG.delivery_fee(0) == 2000
    above_minimum = DeliveryPricingConfig(
        base_fee_ugx=5000,
        price_per_km_ugx=Decimal("500"),
        minimum_fee_ugx=2000,
        rounding_increment_ugx=500,
        max_route_distance_km=Decimal("50"),
    )
    assert above_minimum.delivery_fee(Decimal("0")) == 5000


def test_each_retailer_fulfillment_is_priced_independently() -> None:
    retailer_a, retailer_b = uuid4(), uuid4()
    quote_a = build_delivery_quote(
        TEST_CONFIG, retailer_id=retailer_a, mode=DELIVERY, route_distance_km=Decimal("2")
    )
    quote_b = build_delivery_quote(
        TEST_CONFIG, retailer_id=retailer_b, mode=DELIVERY, route_distance_km=Decimal("5")
    )

    assert quote_a.delivery_fee_ugx == 2000
    assert quote_b.delivery_fee_ugx == 3500
    assert quote_a.delivery_fee_ugx != quote_b.delivery_fee_ugx
    # No averaging and no equal split: the sum of two independent 2 km + 5 km legs
    # (5500) is not one averaged 3.5 km leg.
    assert TEST_CONFIG.delivery_fee(Decimal("3.5")) == 3000
    assert total_delivery_fee([quote_a, quote_b]) != TEST_CONFIG.delivery_fee(Decimal("3.5")) * 2


def test_multi_retailer_delivery_total_is_the_sum_of_fulfillment_fees() -> None:
    quotes = [
        build_delivery_quote(TEST_CONFIG, retailer_id=uuid4(), mode=DELIVERY, route_distance_km=Decimal("2")),
        build_delivery_quote(TEST_CONFIG, retailer_id=uuid4(), mode=DELIVERY, route_distance_km=Decimal("5")),
        build_delivery_quote(TEST_CONFIG, retailer_id=uuid4(), mode=PICKUP),
    ]

    assert total_delivery_fee(quotes) == 5500


def test_negative_route_distance_is_rejected() -> None:
    with pytest.raises(DeliveryPricingError) as error:
        TEST_CONFIG.delivery_fee(Decimal("-0.5"))

    assert error.value.code == "invalid_route_distance"

    with pytest.raises(DeliveryPricingError) as build_error:
        build_delivery_quote(
            TEST_CONFIG, retailer_id=uuid4(), mode=DELIVERY, route_distance_km=Decimal("-2")
        )

    assert build_error.value.code == "invalid_route_distance"


def test_negative_or_zero_pricing_parameters_are_rejected() -> None:
    valid = {
        "base_fee_ugx": 1000,
        "price_per_km_ugx": Decimal("500"),
        "minimum_fee_ugx": 2000,
        "rounding_increment_ugx": 500,
        "max_route_distance_km": Decimal("50"),
    }

    for field, value in (
        ("base_fee_ugx", -1),
        ("price_per_km_ugx", Decimal("-500")),
        ("minimum_fee_ugx", -1),
        ("rounding_increment_ugx", 0),
        ("rounding_increment_ugx", -500),
        ("max_route_distance_km", Decimal("-1")),
        ("max_route_distance_km", Decimal("0")),
    ):
        invalid = {**valid, field: value}
        with pytest.raises(DeliveryPricingError) as error:
            DeliveryPricingConfig(**invalid)
        assert error.value.code == "invalid_pricing_configuration"

    with pytest.raises(DeliveryPricingError) as from_mapping_error:
        DeliveryPricingConfig.from_mapping({**valid, "base_fee_ugx": -1})
    assert from_mapping_error.value.code == "invalid_pricing_configuration"


def test_invalid_pricing_configuration_blocks_delivery_checkout(database) -> None:
    fixture = pricing_fixture(database, retailer_count=1)
    database.add(PlatformSetting(key=PRICING_SETTING_KEY, value={"base_fee_ugx": -1}))
    database.commit()

    with pytest.raises(DeliveryPricingError) as error:
        resolve_delivery_pricing_config(database)

    assert error.value.code == "invalid_pricing_configuration"

    with pytest.raises(HTTPException) as http_error:
        create_order(
            database,
            fixture["customer"],
            CheckoutIn(
                delivery_method="DELIVERY",
                delivery_point_id=fixture["point"].id,
            ),
            "invalid-pricing-config-key",
        )

    assert http_error.value.status_code == 503
    assert http_error.value.detail["code"] == "invalid_platform_setting"


def test_monetary_calculation_avoids_binary_float_drift() -> None:
    exact = DeliveryPricingConfig(
        base_fee_ugx=0,
        price_per_km_ugx=Decimal("1"),
        minimum_fee_ugx=0,
        rounding_increment_ugx=1,
        max_route_distance_km=Decimal("50"),
    )

    # Halfway values round up deterministically. Python's round(0.5) is 0, so a
    # float-based implementation would produce 0 here.
    assert exact.delivery_fee(Decimal("0.5")) == 1
    assert exact.delivery_fee(Decimal("1.5")) == 2
    assert exact.delivery_fee(Decimal("2.5")) == 3
    # 0.1 is not representable in binary floating point; Decimal pricing keeps it exact.
    assert exact.delivery_fee("0.1") == 0
    assert exact.delivery_fee(Decimal("2.675")) == 3
    fee = exact.delivery_fee(Decimal("3"))
    assert isinstance(fee, int)
    assert not isinstance(fee, bool)
    assert fee == 3


def test_rounding_tie_break_is_configurable_and_snapshotted() -> None:
    rounds_up = DeliveryPricingConfig(
        base_fee_ugx=0,
        price_per_km_ugx=Decimal("1000"),
        minimum_fee_ugx=0,
        rounding_increment_ugx=500,
        max_route_distance_km=Decimal("50"),
        rounding_tie_break="UP",
    )
    rounds_down = DeliveryPricingConfig(
        base_fee_ugx=0,
        price_per_km_ugx=Decimal("1000"),
        minimum_fee_ugx=0,
        rounding_increment_ugx=500,
        max_route_distance_km=Decimal("50"),
        rounding_tie_break="DOWN",
    )

    # 0.25 km x 1000 = 250 UGX, exactly halfway between 0 and 500.
    assert rounds_up.delivery_fee(Decimal("0.25")) == 500
    assert rounds_down.delivery_fee(Decimal("0.25")) == 0

    quote = build_delivery_quote(
        rounds_up, retailer_id=uuid4(), mode=DELIVERY, route_distance_km=Decimal("0.25")
    )
    assert quote.rounding_tie_break == "UP"

    with pytest.raises(DeliveryPricingError) as error:
        DeliveryPricingConfig(
            base_fee_ugx=0,
            price_per_km_ugx=Decimal("1000"),
            minimum_fee_ugx=0,
            rounding_increment_ugx=500,
            max_route_distance_km=Decimal("50"),
            rounding_tie_break="SIDEWAYS",
        )
    assert error.value.code == "invalid_pricing_configuration"


def test_route_distance_beyond_the_configured_maximum_is_refused() -> None:
    assert APPROVED_DELIVERY_PRICING_CONFIG.delivery_fee(Decimal("15")) == 9000

    with pytest.raises(DeliveryPricingError) as approved_error:
        APPROVED_DELIVERY_PRICING_CONFIG.delivery_fee(Decimal("15.001"))
    assert approved_error.value.code == "route_distance_exceeds_maximum"

    with pytest.raises(DeliveryPricingError) as test_error:
        TEST_CONFIG.delivery_fee(Decimal("50.5"))
    assert test_error.value.code == "route_distance_exceeds_maximum"


def test_route_distance_precision_beyond_three_decimals_is_refused() -> None:
    with pytest.raises(DeliveryPricingError) as error:
        TEST_CONFIG.delivery_fee(Decimal("1.2345"))

    assert error.value.code == "route_distance_precision_unsupported"
    assert TEST_CONFIG.delivery_fee(Decimal("1.234")) == 2000



def _quote_for_order(database, order) -> DeliveryQuote:
    return database.scalar(
        select(DeliveryQuote)
        .join(RetailerFulfillment, RetailerFulfillment.id == DeliveryQuote.fulfillment_id)
        .where(RetailerFulfillment.order_id == order.id)
    )


def test_committed_quote_snapshot_preserves_pricing_inputs(database, fake_routing) -> None:
    fixture = pricing_fixture(database, retailer_count=1)
    configure_routes(fixture, fake_routing, [5])
    order = create_order(
        database,
        fixture["customer"],
        CheckoutIn(
            delivery_method="DELIVERY",
            delivery_point_id=fixture["point"].id,
        ),
        "snapshot-key-0001",
    )
    database.commit()
    quote = _quote_for_order(database, order)

    assert quote is not None
    assert quote.retailer_id == fixture["retailers"][0].id
    assert quote.mode == "DELIVERY"
    # The distance came from the routing service, not from a caller.
    assert quote.distance_source == fake_routing.source
    assert quote.route_distance_km == Decimal("5")
    assert quote.base_fee_ugx == 1500
    assert quote.price_per_km_ugx == Decimal("500")
    assert quote.minimum_fee_ugx == 2500
    assert quote.rounding_increment_ugx == 500
    assert quote.rounding_tie_break == "UP"
    assert quote.currency == "UGX"
    assert quote.pricing_version
    assert quote.delivery_fee_ugx == 4000
    assert quote.quoted_at is not None
    assert quote.removed_at is None
    assert order.delivery_fee_ugx == 4000
    assert order.total_ugx == order.subtotal_ugx + 4000


def test_committed_quote_keeps_distance_precision(database, fake_routing) -> None:
    fixture = pricing_fixture(database, retailer_count=1)
    configure_routes(fixture, fake_routing, ["2.345"])
    order = create_order(
        database,
        fixture["customer"],
        CheckoutIn(
            delivery_method="DELIVERY",
            delivery_point_id=fixture["point"].id,
        ),
        "snapshot-precision-key",
    )
    database.commit()
    quote = _quote_for_order(database, order)

    assert quote is not None
    assert quote.route_distance_km == Decimal("2.345")
    # 1500 + (2.345 x 500) = 2672.5 UGX, rounded to the nearest UGX 500 increment.
    assert quote.delivery_fee_ugx == 2500


def test_later_pricing_configuration_change_does_not_mutate_committed_quote(database, fake_routing) -> None:
    fixture = pricing_fixture(database, retailer_count=1)
    configure_routes(fixture, fake_routing, [5])
    order = create_order(
        database,
        fixture["customer"],
        CheckoutIn(
            delivery_method="DELIVERY",
            delivery_point_id=fixture["point"].id,
        ),
        "config-change-key",
    )
    database.commit()
    committed_total = order.total_ugx
    quote = _quote_for_order(database, order)

    database.add(
        PlatformSetting(
            key=PRICING_SETTING_KEY,
            value={
                "base_fee_ugx": 10_000,
                "price_per_km_ugx": 10_000,
                "minimum_fee_ugx": 10_000,
                "rounding_increment_ugx": 500,
                "max_route_distance_km": 50,
            },
        )
    )
    database.commit()
    updated_config = resolve_delivery_pricing_config(database)

    # The new configuration prices a new quote differently ...
    assert updated_config.delivery_fee(Decimal("5")) == 60_000
    assert updated_config.base_fee_ugx == 10_000
    # ... but the already-created order and its snapshot keep their committed values.
    database.refresh(order)
    database.refresh(quote)
    assert order.delivery_fee_ugx == 4000
    assert order.total_ugx == committed_total
    assert quote.delivery_fee_ugx == 4000
    assert quote.base_fee_ugx == 1500
    assert quote.price_per_km_ugx == Decimal("500")



def test_checkout_prices_each_retailer_leg_from_the_routing_service(database, fake_routing) -> None:
    fixture = pricing_fixture(database, retailer_count=2)
    configure_routes(fixture, fake_routing, ["2", "5"])

    order = create_order(
        database,
        fixture["customer"],
        CheckoutIn(delivery_method="DELIVERY", delivery_point_id=fixture["point"].id),
        "routed-checkout-key",
    )
    database.commit()
    quotes = {
        quote.retailer_id: quote
        for quote in database.scalars(
            select(DeliveryQuote)
            .join(RetailerFulfillment, RetailerFulfillment.id == DeliveryQuote.fulfillment_id)
            .where(RetailerFulfillment.order_id == order.id)
        ).all()
    }

    # One road route per retailer leg, priced independently (COM-FEE-001/002).
    assert len(fake_routing.route_calls) == 2
    assert quotes[fixture["retailers"][0].id].route_distance_km == Decimal("2")
    assert quotes[fixture["retailers"][1].id].route_distance_km == Decimal("5")
    assert {quote.distance_source for quote in quotes.values()} == {fake_routing.source}
    # 2 km -> UGX 2,500 and 5 km -> UGX 4,000; the combined UGX 6,500
    # delivery fee receives one 15% multi-retailer consolidation discount.
    assert order.gross_delivery_fee_ugx == 6500
    assert order.multi_retailer_discount_ugx == 975
    assert order.multi_retailer_discount_percent == Decimal("15")
    assert order.delivery_fee_ugx == 5525
    assert order.total_ugx == order.subtotal_ugx + 5525


def test_client_supplied_distances_never_reach_pricing(database, fake_routing) -> None:
    """A hard-coded or caller-supplied distance cannot influence the fee."""

    fixture = pricing_fixture(database, retailer_count=1)
    configure_routes(fixture, fake_routing, [5])

    order = create_order(
        database,
        fixture["customer"],
        CheckoutIn(
            delivery_method="DELIVERY",
            delivery_point_id=fixture["point"].id,
            # Ignored: the checkout schema has no distance field any more.
            delivery_route_distance_km={fixture["retailers"][0].id: Decimal("0.1")},
        ),
        "client-distance-key",
    )
    database.commit()
    quote = _quote_for_order(database, order)

    assert quote.route_distance_km == Decimal("5")
    assert quote.delivery_fee_ugx == 4000


def test_route_beyond_the_configured_maximum_refuses_checkout(database, fake_routing) -> None:
    fixture = pricing_fixture(database, retailer_count=2)
    configure_routes(fixture, fake_routing, ["40", "3"])

    with pytest.raises(HTTPException) as error:
        create_order(
            database,
            fixture["customer"],
            CheckoutIn(delivery_method="DELIVERY", delivery_point_id=fixture["point"].id),
            "over-maximum-distance-key",
        )

    assert error.value.status_code == 422
    assert error.value.detail["code"] == "route_distance_exceeds_maximum"


def test_routing_failure_refuses_delivery_checkout(database, fake_routing) -> None:
    """COM-FEE-009: when no route can be produced, refuse — never guess."""

    fixture = pricing_fixture(database, retailer_count=1)
    fake_routing.route_error = RoutingProviderError(
        "no_route_found", "No road route connects those two locations."
    )

    with pytest.raises(HTTPException) as error:
        create_order(
            database,
            fixture["customer"],
            CheckoutIn(delivery_method="DELIVERY", delivery_point_id=fixture["point"].id),
            "routing-failure-key",
        )

    assert error.value.status_code == 503
    assert error.value.detail["code"] == "delivery_route_unavailable"
    database.rollback()
    assert database.scalars(select(Order)).all() == []


def test_unresolvable_delivery_point_refuses_checkout(database, fake_routing) -> None:
    fixture = pricing_fixture(database, retailer_count=1)
    point = fixture["point"]
    point.latitude = None
    point.longitude = None
    fake_routing.geocode_returns_none = True
    database.commit()

    with pytest.raises(HTTPException) as error:
        create_order(
            database,
            fixture["customer"],
            CheckoutIn(delivery_method="DELIVERY", delivery_point_id=fixture["point"].id),
            "unresolved-location-key",
        )

    assert error.value.status_code == 422
    assert error.value.detail["code"] == "delivery_location_unresolved"
    assert fake_routing.geocode_calls


def test_pickup_checkout_never_contacts_the_routing_service(database, fake_routing) -> None:
    fixture = pricing_fixture(database, retailer_count=1)

    order = create_order(
        database,
        fixture["customer"],
        CheckoutIn(delivery_method="PICKUP", pickup_point_id=fixture["pickup_point"].delivery_point_id),
        "pickup-no-routing-key",
    )
    database.commit()

    assert fake_routing.route_calls == []
    assert fake_routing.geocode_calls == []
    assert order.delivery_fee_ugx == 0


def test_pickup_checkout_records_zero_delivery_quotes(database) -> None:
    result = pricing_fixture(database, retailer_count=2)
    order = create_order(
        database,
        result["customer"],
        CheckoutIn(delivery_method="PICKUP", pickup_point_id=result["pickup_point"].delivery_point_id),
        "pickup-quote-key",
    )
    database.commit()
    quotes = database.scalars(
        select(DeliveryQuote)
        .join(RetailerFulfillment, RetailerFulfillment.id == DeliveryQuote.fulfillment_id)
        .where(RetailerFulfillment.order_id == order.id)
    ).all()

    assert order.delivery_fee_ugx == 0
    assert order.total_ugx == order.subtotal_ugx
    assert len(quotes) == 2
    assert {quote.mode for quote in quotes} == {"PICKUP"}
    assert {quote.delivery_fee_ugx for quote in quotes} == {0}
    assert {quote.route_distance_km for quote in quotes} == {None}


def test_checkout_without_caller_supplied_distances_uses_routing(database, fake_routing) -> None:
    result = pricing_fixture(database, retailer_count=2)
    configure_routes(result, fake_routing, ["2", "5"])
    order = create_order(
        database,
        result["customer"],
        CheckoutIn(delivery_method="DELIVERY", delivery_point_id=result["point"].id),
        "flat-fee-key",
    )
    database.commit()

    # The caller never supplies distances; checkout obtains one road route per retailer.
    assert order.delivery_fee_ugx == 6500
    assert order.total_ugx == order.subtotal_ugx + 6500
    assert len(database.scalars(select(DeliveryQuote)).all()) == 2

    assert total_delivery_fee([]) == 0



def test_rejected_fulfillment_removes_only_its_own_committed_fee(database, fake_routing) -> None:
    result = pricing_fixture(database, retailer_count=2)
    configure_routes(result, fake_routing, ["2", "5"])
    order = create_order(
        database,
        result["customer"],
        CheckoutIn(
            delivery_method="DELIVERY",
            delivery_point_id=result["point"].id,
            delivery_route_distance_km={
                result["retailers"][0].id: Decimal("2"),
                result["retailers"][1].id: Decimal("5"),
            },
        ),
        "rejection-quote-key",
    )
    database.commit()
    assert order.delivery_fee_ugx == 6500
    assert order.total_ugx == order.subtotal_ugx + 6500

    fulfillments = {
        fulfillment.retailer_id: fulfillment
        for fulfillment in database.scalars(
            select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id)
        ).all()
    }
    rejected = fulfillments[result["retailers"][0].id]

    _adjust_order_after_rejection(database, order, rejected)
    rejected.status = "REJECTED"
    database.commit()

    quotes = {quote.retailer_id: quote for quote in database.scalars(select(DeliveryQuote)).all()}
    assert order.delivery_fee_ugx == 4000
    assert order.total_ugx == order.subtotal_ugx + 4000
    assert quotes[result["retailers"][0].id].removed_at is not None
    assert quotes[result["retailers"][1].id].removed_at is None
    assert quotes[result["retailers"][1].id].delivery_fee_ugx == 4000
    # A second removal is not possible: the committed fee is gone.
    assert remove_committed_delivery_quote(database, rejected.id) is None


def test_committed_order_total_is_used_for_online_payment_creation(client, database, fake_routing, monkeypatch) -> None:
    result = pricing_fixture(database, retailer_count=1)
    configure_routes(result, fake_routing, ["5"])
    order = create_order(
        database,
        result["customer"],
        CheckoutIn(
            delivery_method="DELIVERY",
            delivery_point_id=result["point"].id,
            delivery_route_distance_km={result["retailers"][0].id: Decimal("5")},
        ),
        "payment-total-key",
    )
    database.commit()

    class FakeMomoProvider:
        name = "TEST_MTN_MOMO"

        def initiate(self, request):
            assert request.amount_ugx == order.total_ugx == 14_000
            return PaymentInitiation(provider_reference="test-provider-reference")

        def verify_webhook(self, raw_body, signature):
            return True

    monkeypatch.setitem(payment_providers._providers, "MTN_MOMO", FakeMomoProvider())

    response = client.post(
        f"/api/v1/orders/{order.id}/payments",
        headers=_authorization(database, result["customer"]),
        json={"method": "MTN_MOMO", "phone": "+256700000001"},
    )

    assert response.status_code == 201
    assert response.json()["amount_ugx"] == 14_000
    assert response.json()["amount_ugx"] == order.subtotal_ugx + order.delivery_fee_ugx

def test_missing_retailer_pickup_location_refuses_delivery_checkout(database, fake_routing) -> None:
    """A delivery quote must never guess a retailer location from its business name."""

    fixture = pricing_fixture(database, retailer_count=1)
    retailer = fixture["retailers"][0]
    retailer.location_id = None
    database.commit()

    with pytest.raises(HTTPException) as error:
        create_order(
            database,
            fixture["customer"],
            CheckoutIn(
                delivery_method="DELIVERY",
                delivery_point_id=fixture["point"].id,
            ),
            "missing-retailer-location-key",
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "retailer_location_required"
    assert "pickup location" in error.value.detail["message"].lower()
    assert fake_routing.route_calls == []

