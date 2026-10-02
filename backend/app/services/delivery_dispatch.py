"""Instant delivery dispatch and short-lived rider offers.

Dispatch uses rider GPS proximity only as an operational selection signal.
Commercial delivery pricing and road-route calculation remain in the existing
checkout/pricing services.
"""

from __future__ import annotations

from datetime import timedelta
from math import asin, cos, radians, sin, sqrt
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DeliveryAgent,
    DeliveryAgentLocation,
    DeliveryAssignment,
    DeliveryEvent,
    DeliveryOffer,
    DeliveryPoint,
    NotificationOutbox,
    Order,
    Retailer,
    RetailerFulfillment,
    utcnow,
)

RIDER_LOCATION_MAX_AGE_SECONDS = 60
OFFER_TTL_SECONDS = 20


class DispatchError(Exception):
    """Base dispatch error."""


class OfferUnavailableError(DispatchError):
    """The requested offer is no longer actionable."""


def haversine_distance_m(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    earth_radius_m = 6_371_000.0
    lat1, lat2 = radians(latitude_a), radians(latitude_b)
    dlat = radians(latitude_b - latitude_a)
    dlon = radians(longitude_b - longitude_a)
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(a))


def _active_assignment_exists(db: Session, agent_id: UUID) -> bool:
    return db.scalar(
        select(DeliveryAssignment.id).where(
            DeliveryAssignment.agent_id == agent_id,
            DeliveryAssignment.status.in_({"ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY"}),
        ).limit(1)
    ) is not None


def _candidate_rows(db: Session, assignment: DeliveryAssignment) -> list[tuple[DeliveryAgent, DeliveryAgentLocation, float]]:
    pickup = db.get(DeliveryPoint, assignment.pickup_point_id) if assignment.pickup_point_id else None
    if pickup is None or pickup.latitude is None or pickup.longitude is None:
        return []

    rows = db.execute(
        select(DeliveryAgent, DeliveryAgentLocation)
        .join(DeliveryAgentLocation, DeliveryAgentLocation.agent_id == DeliveryAgent.user_id)
        .where(
            DeliveryAgent.verification_status == "VERIFIED",
            DeliveryAgent.availability_status == "AVAILABLE",
            DeliveryAgentLocation.updated_at >= utcnow() - timedelta(seconds=RIDER_LOCATION_MAX_AGE_SECONDS),
        )
    ).all()

    prior_agents = set(
        db.scalars(
            select(DeliveryOffer.agent_id)
            .where(DeliveryOffer.assignment_id == assignment.id)
        ).all()
    )
    candidates: list[tuple[DeliveryAgent, DeliveryAgentLocation, float]] = []
    for agent, location in rows:
        if agent.user_id in prior_agents or _active_assignment_exists(db, agent.user_id):
            continue
        distance_m = haversine_distance_m(
            float(location.latitude),
            float(location.longitude),
            float(pickup.latitude),
            float(pickup.longitude),
        )
        candidates.append((agent, location, distance_m))

    candidates.sort(key=lambda row: (row[2], row[1].updated_at, str(row[0].user_id)))
    return candidates


def _create_offer(db: Session, assignment: DeliveryAssignment) -> DeliveryOffer | None:
    candidates = _candidate_rows(db, assignment)
    if not candidates:
        return None

    next_sequence = (
        db.scalar(
            select(DeliveryOffer.offer_sequence)
            .where(DeliveryOffer.assignment_id == assignment.id)
            .order_by(DeliveryOffer.offer_sequence.desc())
            .limit(1)
        )
        or 0
    ) + 1
    agent, _location, distance_m = candidates[0]
    now = utcnow()
    offer = DeliveryOffer(
        assignment_id=assignment.id,
        agent_id=agent.user_id,
        status="PENDING",
        offer_sequence=next_sequence,
        offered_at=now,
        expires_at=now + timedelta(seconds=OFFER_TTL_SECONDS),
        distance_m=distance_m,
    )
    db.add(offer)
    db.flush()

    fulfillment = db.get(RetailerFulfillment, assignment.fulfillment_id)
    order = db.get(Order, fulfillment.order_id) if fulfillment else None
    retailer = db.get(Retailer, fulfillment.retailer_id) if fulfillment else None
    pickup = db.get(DeliveryPoint, assignment.pickup_point_id) if assignment.pickup_point_id else None
    db.add(
        NotificationOutbox(
            user_id=agent.user_id,
            event_type="DELIVERY_OFFER",
            payload={
                "offer_id": str(offer.id),
                "assignment_id": str(assignment.id),
                "order_number": order.order_number if order else None,
                "retailer_name": retailer.business_name if retailer else None,
                "pickup_name": pickup.name if pickup else None,
                "distance_m": round(distance_m, 2),
                "expires_at": offer.expires_at.isoformat(),
            },
        )
    )
    return offer


def advance_dispatch(db: Session, assignment_id: UUID) -> DeliveryOffer | None:
    assignment = db.scalar(
        select(DeliveryAssignment)
        .where(DeliveryAssignment.id == assignment_id)
        .with_for_update()
    )
    if assignment is None or assignment.status != "UNASSIGNED":
        return None

    fulfillment = db.get(RetailerFulfillment, assignment.fulfillment_id)
    if fulfillment is None or fulfillment.status != "READY":
        return None

    pending = db.scalar(
        select(DeliveryOffer)
        .where(
            DeliveryOffer.assignment_id == assignment.id,
            DeliveryOffer.status == "PENDING",
        )
        .order_by(DeliveryOffer.offer_sequence.desc())
        .with_for_update()
    )
    now = utcnow()
    if pending is not None:
        if pending.expires_at > now:
            return pending
        pending.status = "EXPIRED"
        pending.responded_at = now

    return _create_offer(db, assignment)


def dispatch_ready_fulfillment(db: Session, fulfillment_id: UUID) -> DeliveryOffer | None:
    fulfillment = db.scalar(
        select(RetailerFulfillment)
        .where(RetailerFulfillment.id == fulfillment_id)
        .with_for_update()
    )
    if fulfillment is None or fulfillment.status != "READY":
        return None
    assignment = db.scalar(
        select(DeliveryAssignment)
        .where(DeliveryAssignment.fulfillment_id == fulfillment.id)
        .with_for_update()
    )
    if assignment is None:
        return None
    return advance_dispatch(db, assignment.id)


def dispatch_ready_queue(db: Session, limit: int = 20) -> int:
    assignments = db.scalars(
        select(DeliveryAssignment)
        .join(RetailerFulfillment, RetailerFulfillment.id == DeliveryAssignment.fulfillment_id)
        .where(
            DeliveryAssignment.status == "UNASSIGNED",
            RetailerFulfillment.status == "READY",
        )
        .order_by(DeliveryAssignment.created_at)
        .limit(limit)
    ).all()
    count = 0
    for assignment in assignments:
        if dispatch_ready_fulfillment(db, assignment.fulfillment_id) is not None:
            count += 1
    return count


def offer_view(db: Session, offer: DeliveryOffer) -> dict:
    assignment = db.get(DeliveryAssignment, offer.assignment_id)
    fulfillment = db.get(RetailerFulfillment, assignment.fulfillment_id) if assignment else None
    order = db.get(Order, fulfillment.order_id) if fulfillment else None
    retailer = db.get(Retailer, fulfillment.retailer_id) if fulfillment else None
    pickup = db.get(DeliveryPoint, assignment.pickup_point_id) if assignment and assignment.pickup_point_id else None
    return {
        "id": offer.id,
        "assignment_id": offer.assignment_id,
        "agent_id": offer.agent_id,
        "status": offer.status,
        "offer_sequence": offer.offer_sequence,
        "offered_at": offer.offered_at,
        "expires_at": offer.expires_at,
        "responded_at": offer.responded_at,
        "distance_m": float(offer.distance_m),
        "delivery": {
            "order_number": order.order_number if order else None,
            "retailer_name": retailer.business_name if retailer else None,
            "pickup": {"name": pickup.name, "directions": pickup.directions} if pickup else None,
        },
    }


def list_active_offers(db: Session, agent_id: UUID, limit: int = 20) -> list[dict]:
    offers = db.scalars(
        select(DeliveryOffer)
        .where(
            DeliveryOffer.agent_id == agent_id,
            DeliveryOffer.status == "PENDING",
        )
        .order_by(DeliveryOffer.expires_at.asc(), DeliveryOffer.created_at.asc())
        .limit(limit)
        .with_for_update()
    ).all()
    now = utcnow()
    for offer in offers:
        if offer.expires_at <= now:
            offer.status = "EXPIRED"
            offer.responded_at = now
            advance_dispatch(db, offer.assignment_id)
    db.flush()
    current = db.scalars(
        select(DeliveryOffer)
        .where(
            DeliveryOffer.agent_id == agent_id,
            DeliveryOffer.status == "PENDING",
        )
        .order_by(DeliveryOffer.expires_at.asc(), DeliveryOffer.created_at.asc())
        .limit(limit)
    ).all()
    return [offer_view(db, offer) for offer in current]


def reject_offer(db: Session, agent_id: UUID, offer_id: UUID) -> DeliveryOffer:
    offer = db.scalar(
        select(DeliveryOffer)
        .where(DeliveryOffer.id == offer_id)
        .with_for_update()
    )
    if offer is None or offer.agent_id != agent_id:
        raise OfferUnavailableError("Delivery offer was not found.")
    if offer.status != "PENDING" or offer.expires_at <= utcnow():
        if offer.status == "PENDING":
            offer.status = "EXPIRED"
            offer.responded_at = utcnow()
        raise OfferUnavailableError("Delivery offer has expired or is no longer available.")
    offer.status = "REJECTED"
    offer.responded_at = utcnow()
    advance_dispatch(db, offer.assignment_id)
    return offer


def accept_offer(db: Session, agent_id: UUID, offer_id: UUID) -> DeliveryAssignment:
    offer = db.scalar(
        select(DeliveryOffer)
        .where(DeliveryOffer.id == offer_id)
        .with_for_update()
    )
    if offer is None or offer.agent_id != agent_id:
        raise OfferUnavailableError("Delivery offer was not found.")
    assignment = db.scalar(
        select(DeliveryAssignment)
        .where(DeliveryAssignment.id == offer.assignment_id)
        .with_for_update()
    )
    agent = db.scalar(
        select(DeliveryAgent)
        .where(DeliveryAgent.user_id == agent_id)
        .with_for_update()
    )
    if assignment is None or agent is None:
        raise OfferUnavailableError("Delivery offer is no longer available.")
    if offer.status != "PENDING" or offer.expires_at <= utcnow():
        if offer.status == "PENDING":
            offer.status = "EXPIRED"
            offer.responded_at = utcnow()
        raise OfferUnavailableError("Delivery offer has expired.")
    if assignment.status != "UNASSIGNED":
        offer.status = "CANCELLED"
        raise OfferUnavailableError("This delivery has already been assigned.")
    if agent.verification_status != "VERIFIED" or agent.availability_status != "AVAILABLE":
        raise OfferUnavailableError("You must be verified and available to accept this delivery.")
    if _active_assignment_exists(db, agent_id):
        raise OfferUnavailableError("Complete your active delivery before accepting another.")

    fulfillment = db.get(RetailerFulfillment, assignment.fulfillment_id)
    order = db.get(Order, fulfillment.order_id) if fulfillment else None
    if fulfillment is None or order is None or fulfillment.status != "READY":
        offer.status = "CANCELLED"
        raise OfferUnavailableError("This order is no longer ready for delivery.")

    now = utcnow()
    assignment.agent_id = agent_id
    assignment.status = "ACCEPTED"
    assignment.assigned_at = now
    assignment.accepted_at = now
    agent.availability_status = "BUSY"
    offer.status = "ACCEPTED"
    offer.responded_at = now

    competing = db.scalars(
        select(DeliveryOffer)
        .where(
            DeliveryOffer.assignment_id == assignment.id,
            DeliveryOffer.status == "PENDING",
            DeliveryOffer.id != offer.id,
        )
        .with_for_update()
    ).all()
    for other in competing:
        other.status = "CANCELLED"
        other.responded_at = now

    db.add(
        DeliveryEvent(
            assignment_id=assignment.id,
            actor_user_id=agent_id,
            previous_status="UNASSIGNED",
            new_status="ACCEPTED",
            note="Accepted instant dispatch offer",
        )
    )
    db.add(
        NotificationOutbox(
            user_id=order.customer_id,
            event_type="DELIVERY_ASSIGNED",
            payload={"order_id": str(order.id), "order_number": order.order_number},
        )
    )
    return assignment
