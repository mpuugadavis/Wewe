from decimal import Decimal
from unittest.mock import patch, MagicMock
import pytest
from sqlalchemy import select, func
from app.models import University, Campus, Hall, DeliveryPoint, Order
from app.public_locations import restore_public_locations
from app.services.delivery_routing import resolve_route_distances, DeliveryRoutingError
from app.services.routing import RoutingProviderError, RouteDistance
from test_order_service import marketplace_fixture


def test_public_catalogue_restores_halls_and_hostels_idempotently(database, client):
    university = University(name="Makerere University", slug="makerere-university", country_code="UG")
    database.add(university)
    database.flush()
    campus = Campus(university_id=university.id, name="Main Campus", slug="main-campus")
    database.add(campus)
    database.flush()
    assert restore_public_locations(database) == 21
    assert restore_public_locations(database) == 0
    database.commit()
    halls = client.get(f"/api/v1/locations/halls?campus_id={campus.id}").json()
    points = client.get(f"/api/v1/locations/delivery-points?campus_id={campus.id}").json()
    assert len([h for h in halls if h["kind"] == "HALL"]) == 9
    hostel_ids = {h["id"] for h in halls if h["kind"] == "HOSTEL"}
    assert len(hostel_ids) == 7
    assert len([p for p in points if p["hall_id"] in hostel_ids]) == 7
    assert all(p["latitude"] is not None and p["longitude"] is not None for p in points)
    point = database.scalar(select(DeliveryPoint).where(DeliveryPoint.name == "Africa Hall"))
    point.is_active = False
    point.latitude = Decimal("0.338000")
    restore_public_locations(database)
    assert point.is_active is False
    assert point.latitude == Decimal("0.338000")
    assert database.scalar(select(func.count()).select_from(Order)) == 0


@pytest.mark.parametrize("code, fallback_succeeds", [
    ("routing_provider_unreachable", True),
    ("routing_provider_unreachable", False),
    ("routing_provider_error", False),
    ("no_route_found", False),
])
def test_checkout_uses_auditable_road_fallback_only_for_ors_outages(database, code, fallback_succeeds):
    _customer, point, listing, _inventory = marketplace_fixture(database)
    primary = MagicMock(name="primary")
    primary.name = "OPENROUTESERVICE"
    primary.route_distance.side_effect = RoutingProviderError(code, "Provider unavailable")
    secondary = MagicMock()
    secondary.route_distance.return_value = RouteDistance(Decimal("0.375"), "OSRM_ROAD_ROUTE", "OSRM")
    if not fallback_succeeds:
        secondary.route_distance.side_effect = RoutingProviderError("routing_provider_unreachable", "Unavailable")
    with patch("app.services.delivery_routing.get_routing_provider", return_value=primary), patch(
        "app.services.delivery_routing.OsrmRoutingProvider", return_value=secondary
    ) as fallback:
        if fallback_succeeds:
            distances, provider = resolve_route_distances(database, destination=point, retailer_ids=[listing.retailer_id])
            assert provider == "OSRM"
            assert distances[listing.retailer_id].distance_km == Decimal("0.375")
            assert distances[listing.retailer_id].source == "OSRM_ROAD_ROUTE"
            fallback.assert_called_once_with(base_url="https://router.project-osrm.org", timeout=5)
        else:
            with pytest.raises(DeliveryRoutingError) as error:
                resolve_route_distances(database, destination=point, retailer_ids=[listing.retailer_id])
            assert error.value.status_code == 503
            if code != "routing_provider_unreachable":
                fallback.assert_not_called()
