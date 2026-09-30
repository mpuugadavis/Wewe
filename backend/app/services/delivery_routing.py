"""Resolve WEWE checkout locations into road-route distances (COM-FEE-004).

The delivery-pricing engine prices a distance; this module is what *obtains*
that distance from a routing service. One distance is produced per retailer
fulfillment leg:

    origin      = the retailer's pickup location (``retailers.location_id``)
    destination = the customer's chosen delivery point

Coordinates come from stored ``delivery_points`` coordinates when they exist,
and otherwise from the routing provider's geocoder using the location's real
address text. Nothing here derives a distance from a straight line, and nothing
here accepts a distance from the caller.

When no route can be produced the lookup raises :class:`DeliveryRoutingError`
so checkout can refuse the delivery (COM-FEE-009) instead of guessing.
"""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Block, Campus, DeliveryPoint, Hall, Retailer, University
from app.services.routing import GeoCoordinate, RouteDistance, RoutingProviderError, get_routing_provider


class DeliveryRoutingError(Exception):
    """A road-route distance could not be produced for this checkout."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def as_http_exception(self) -> HTTPException:
        return HTTPException(status_code=self.status_code, detail={"code": self.code, "message": self.message})


def _unavailable(message: str) -> DeliveryRoutingError:
    return DeliveryRoutingError("delivery_route_unavailable", message, status_code=503)


def describe_location(db: Session, point: DeliveryPoint) -> str:
    """Human-readable address used when a location has no stored coordinates."""

    parts: list[str] = [point.name]
    if point.directions:
        parts.append(point.directions)
    if point.block_id:
        block = db.get(Block, point.block_id)
        if block:
            parts.append(block.name)
    if point.hall_id:
        hall = db.get(Hall, point.hall_id)
        if hall:
            parts.append(hall.name)
    campus = db.get(Campus, point.campus_id)
    if campus:
        parts.append(campus.name)
        university = db.get(University, campus.university_id)
        if university:
            parts.append(university.name)
    parts.append("Uganda")
    return ", ".join(part for part in parts if part)


def _coordinate_for_point(db: Session, provider, point: DeliveryPoint, label: str) -> GeoCoordinate:
    if point.latitude is not None and point.longitude is not None:
        try:
            return GeoCoordinate.from_values(point.latitude, point.longitude)
        except RoutingProviderError as exc:
            raise DeliveryRoutingError(
                "delivery_location_invalid",
                f"The coordinates recorded for {label} are not valid.",
            ) from exc
    try:
        coordinate = provider.geocode(describe_location(db, point))
    except RoutingProviderError as exc:
        raise _unavailable("Delivery routing is temporarily unavailable. Please try pickup instead.") from exc
    if coordinate is None:
        raise DeliveryRoutingError(
            "delivery_location_unresolved",
            f"WEWE could not locate {label}. Add coordinates to the delivery point or choose pickup.",
        )
    return coordinate


def _coordinate_for_retailer(db: Session, provider, retailer: Retailer, destination: DeliveryPoint) -> GeoCoordinate:
    if retailer.location_id:
        origin = db.get(DeliveryPoint, retailer.location_id)
        if origin is not None and origin.is_active:
            return _coordinate_for_point(db, provider, origin, f"{retailer.business_name}'s pickup location")
    campus = db.get(Campus, destination.campus_id)
    address = retailer.business_name + (f", {campus.name}" if campus else "") + ", Uganda"
    try:
        coordinate = provider.geocode(address)
    except RoutingProviderError as exc:
        raise _unavailable("Delivery routing is temporarily unavailable. Please try pickup instead.") from exc
    if coordinate is None:
        raise DeliveryRoutingError(
            "retailer_location_unresolved",
            f"WEWE could not locate {retailer.business_name}. Choose pickup or contact the retailer.",
        )
    return coordinate


def resolve_route_distances(
    db: Session,
    *,
    destination: DeliveryPoint,
    retailer_ids: list[UUID],
) -> tuple[dict[UUID, RouteDistance], str]:
    """Return one road-route distance per retailer plus the provider name.

    Raises :class:`DeliveryRoutingError` when the routing service, a stored
    coordinate, or a geocoding lookup cannot produce a route.
    """

    try:
        provider = get_routing_provider()
    except RoutingProviderError as exc:
        raise _unavailable("Delivery routing is not configured. Please choose pickup.") from exc

    destination_coordinate = _coordinate_for_point(db, provider, destination, "your delivery point")

    distances: dict[UUID, RouteDistance] = {}
    for retailer_id in retailer_ids:
        retailer = db.get(Retailer, retailer_id)
        if retailer is None:
            raise DeliveryRoutingError(
                "retailer_location_unresolved", "One of the retailers in this order could not be found."
            )
        origin_coordinate = _coordinate_for_retailer(db, provider, retailer, destination)
        origin_place_id = None
        if retailer.location_id:
            retailer_location = db.get(DeliveryPoint, retailer.location_id)
            if retailer_location is not None:
                origin_place_id = retailer_location.google_place_id
        try:
            route = provider.route_distance(
                origin_coordinate,
                destination_coordinate,
                origin_place_id=origin_place_id,
                destination_place_id=destination.google_place_id,
            )
        except RoutingProviderError as exc:
            raise _unavailable(
                "WEWE could not calculate a road route for this delivery. Please try again or choose pickup."
            ) from exc
        distances[retailer_id] = route
    return distances, provider.name

