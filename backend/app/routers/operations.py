from datetime import datetime, timezone
from hmac import compare_digest
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import Principal, require_roles
from app.limiter import limiter
from app.models import (
    DeliveryAgent,
    DeliveryAgentLocation,
    DeliveryAssignment,
    DeliveryEvent,
    DeliveryEarning,
    DeliveryPoint,
    Inventory,
    NotificationOutbox,
    Order,
    OrderItem,
    Product,
    RefreshTokenFamily,
    Retailer,
    RetailerFulfillment,
    Review,
    User,
    WishlistItem,
    utcnow,
)
from app.routers.commerce import _consume_fulfillment_inventory
from app.schemas import (
    AvailabilityUpdate,
    DeliveryAgentLocationOut,
    DeliveryAgentLocationUpdate,
    DeliveryStatusUpdate,
    ReviewCreate,
    WishlistIn,
)
from app.security import hash_token
from app.services.delivery_dispatch import (
    OfferUnavailableError,
    accept_offer,
    dispatch_ready_queue,
    list_active_offers,
    offer_view,
    reject_offer,
)
from app.services.orders import recompute_order_status
from app.services.state_transitions import (
    is_delivery_assignment_transition_allowed,
    is_fulfillment_transition_allowed,
)

router = APIRouter(tags=["delivery", "reviews", "wishlist", "notifications"])


def _agent_profile(db: Session, user_id: UUID, verified: bool = True) -> DeliveryAgent:
    agent = db.get(DeliveryAgent, user_id)
    if agent is None:
        raise HTTPException(status_code=404, detail={"code": "agent_profile_missing", "message": "Delivery profile was not found."})
    if verified and agent.verification_status != "VERIFIED":
        raise HTTPException(status_code=403, detail={"code": "agent_not_verified", "message": "A verified delivery profile is required."})
    return agent


def _delivery_view(db: Session, assignment: DeliveryAssignment, reveal_destination: bool) -> dict:
    fulfillment = db.get(RetailerFulfillment, assignment.fulfillment_id)
    order = db.get(Order, fulfillment.order_id) if fulfillment else None
    retailer = db.get(Retailer, fulfillment.retailer_id) if fulfillment else None
    pickup = db.get(DeliveryPoint, assignment.pickup_point_id) if assignment.pickup_point_id else None
    dropoff = db.get(DeliveryPoint, assignment.dropoff_point_id) if assignment.dropoff_point_id and reveal_destination else None
    return {
        "id": assignment.id,
        "order_id": order.id if order else None,
        "order_number": order.order_number if order else None,
        "fulfillment_id": fulfillment.id if fulfillment else None,
        "retailer_name": retailer.business_name if retailer else None,
        "status": assignment.status,
        "pickup": {"name": pickup.name, "directions": pickup.directions} if pickup else None,
        "dropoff": {"name": dropoff.name, "directions": dropoff.directions} if dropoff else None,
        "assigned_at": assignment.assigned_at,
        "accepted_at": assignment.accepted_at,
        "picked_up_at": assignment.picked_up_at,
        "delivered_at": assignment.delivered_at,
    }


@router.patch("/deliveries/me/availability")
def set_availability(
    payload: AvailabilityUpdate,
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> dict:
    agent = _agent_profile(db, principal.user.id)
    active = db.scalar(
        select(DeliveryAssignment.id).where(
            DeliveryAssignment.agent_id == principal.user.id,
            DeliveryAssignment.status.in_(["ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY"]),
        )
    )
    if active and payload.availability_status == "OFFLINE":
        raise HTTPException(status_code=409, detail={"code": "active_delivery", "message": "Complete your active delivery before going offline."})
    agent.availability_status = payload.availability_status
    if payload.availability_status == "AVAILABLE":
        dispatch_ready_queue(db)
    db.commit()
    return {"availability_status": agent.availability_status}


@router.patch("/deliveries/me/location", response_model=DeliveryAgentLocationOut)
def update_delivery_agent_location(
    payload: DeliveryAgentLocationUpdate,
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> DeliveryAgentLocation:
    agent = db.scalar(
        select(DeliveryAgent)
        .where(DeliveryAgent.user_id == principal.user.id)
        .with_for_update()
    )
    if agent is None:
        raise HTTPException(status_code=404, detail={"code": "agent_profile_missing", "message": "Delivery profile was not found."})
    if agent.verification_status != "VERIFIED":
        raise HTTPException(status_code=403, detail={"code": "agent_not_verified", "message": "A verified delivery profile is required."})
    if agent.availability_status == "OFFLINE":
        raise HTTPException(status_code=409, detail={"code": "agent_offline", "message": "Set delivery availability to available before sharing location."})

    location = db.get(DeliveryAgentLocation, principal.user.id)
    if location is None:
        location = DeliveryAgentLocation(agent_id=principal.user.id)
        db.add(location)

    location.latitude = payload.latitude
    location.longitude = payload.longitude
    location.accuracy_m = payload.accuracy_m
    location.heading_deg = payload.heading_deg
    location.speed_mps = payload.speed_mps
    location.updated_at = utcnow()
    db.commit()
    db.refresh(location)
    return location


@router.get("/deliveries/me/location", response_model=DeliveryAgentLocationOut)
def get_delivery_agent_location(
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> DeliveryAgentLocation:
    _agent_profile(db, principal.user.id)
    location = db.get(DeliveryAgentLocation, principal.user.id)
    if location is None:
        raise HTTPException(status_code=404, detail={"code": "location_not_found", "message": "No rider location has been recorded yet."})
    return location


@router.get("/orders/{order_id}/tracking")
def customer_order_tracking(
    order_id: UUID,
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> dict:
    order = db.get(Order, order_id)
    if order is None or order.customer_id != principal.user.id:
        raise HTTPException(status_code=404, detail={"code": "order_not_found", "message": "Order was not found."})

    assignments = db.execute(
        select(DeliveryAssignment, RetailerFulfillment, Retailer)
        .join(RetailerFulfillment, RetailerFulfillment.id == DeliveryAssignment.fulfillment_id)
        .join(Retailer, Retailer.id == RetailerFulfillment.retailer_id)
        .where(RetailerFulfillment.order_id == order.id)
        .order_by(DeliveryAssignment.created_at)
    ).all()

    now = utcnow()
    deliveries = []
    for assignment, fulfillment, retailer in assignments:
        pickup = db.get(DeliveryPoint, assignment.pickup_point_id) if assignment.pickup_point_id else None
        dropoff = db.get(DeliveryPoint, assignment.dropoff_point_id) if assignment.dropoff_point_id else None

        rider = None
        location = None
        location_status = "UNAVAILABLE"
        if assignment.agent_id is not None and assignment.status not in {"UNASSIGNED", "CANCELLED", "DELIVERED"}:
            agent = db.get(DeliveryAgent, assignment.agent_id)
            rider_user = db.get(User, assignment.agent_id)
            if agent is not None and rider_user is not None:
                rider = {
                    "name": rider_user.name,
                    "transport_mode": agent.transport_mode,
                }
                rider_location = db.get(DeliveryAgentLocation, assignment.agent_id)
                if rider_location is not None:
                    location_updated_at = rider_location.updated_at
                    if location_updated_at.tzinfo is None:
                        location_updated_at = location_updated_at.replace(tzinfo=timezone.utc)
                    age_seconds = max(0.0, (now - location_updated_at).total_seconds())
                    if age_seconds <= 60:
                        location_status = "LIVE"
                        location = {
                            "latitude": float(rider_location.latitude),
                            "longitude": float(rider_location.longitude),
                            "accuracy_m": float(rider_location.accuracy_m),
                            "heading_deg": float(rider_location.heading_deg) if rider_location.heading_deg is not None else None,
                            "speed_mps": float(rider_location.speed_mps) if rider_location.speed_mps is not None else None,
                            "updated_at": rider_location.updated_at,
                        }
                    else:
                        location_status = "STALE"

        deliveries.append({
            "assignment_id": assignment.id,
            "fulfillment_id": fulfillment.id,
            "retailer_name": retailer.business_name,
            "status": assignment.status,
            "location_status": location_status,
            "rider": rider,
            "location": location,
            "pickup": {
                "name": pickup.name,
                "directions": pickup.directions,
                "latitude": float(pickup.latitude) if pickup and pickup.latitude is not None else None,
                "longitude": float(pickup.longitude) if pickup and pickup.longitude is not None else None,
            } if pickup else None,
            "dropoff": {
                "name": dropoff.name,
                "directions": dropoff.directions,
                "latitude": float(dropoff.latitude) if dropoff and dropoff.latitude is not None else None,
                "longitude": float(dropoff.longitude) if dropoff and dropoff.longitude is not None else None,
            } if dropoff else None,
        })

    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "deliveries": deliveries,
        "updated_at": now,
    }


@router.get("/deliveries/me/offers")
def my_delivery_offers(
    limit: int = Query(default=20, ge=1, le=50),
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> list[dict]:
    _agent_profile(db, principal.user.id)
    offers = list_active_offers(db, principal.user.id, limit=limit)
    db.commit()
    return offers


@router.post("/deliveries/offers/{offer_id}/accept")
@limiter.limit("20/minute")
def accept_delivery_offer(
    request: Request,
    offer_id: UUID,
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        assignment = accept_offer(db, principal.user.id, offer_id)
    except OfferUnavailableError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "delivery_offer_unavailable", "message": str(exc)},
        ) from exc
    db.commit()
    return _delivery_view(db, assignment, reveal_destination=True)


@router.post("/deliveries/offers/{offer_id}/reject")
@limiter.limit("20/minute")
def reject_delivery_offer(
    request: Request,
    offer_id: UUID,
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        offer = reject_offer(db, principal.user.id, offer_id)
    except OfferUnavailableError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "delivery_offer_unavailable", "message": str(exc)},
        ) from exc
    db.commit()
    return offer_view(db, offer)


@router.get("/deliveries/available")
def available_deliveries(
    limit: int = Query(default=30, ge=1, le=100),
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> list[dict]:
    agent = _agent_profile(db, principal.user.id)
    if agent.availability_status != "AVAILABLE":
        return []
    assignments = db.scalars(
        select(DeliveryAssignment)
        .join(RetailerFulfillment, RetailerFulfillment.id == DeliveryAssignment.fulfillment_id)
        .where(DeliveryAssignment.status == "UNASSIGNED", RetailerFulfillment.status == "READY")
        .order_by(DeliveryAssignment.created_at)
        .limit(limit)
    ).all()
    return [_delivery_view(db, assignment, reveal_destination=False) for assignment in assignments]


@router.post("/deliveries/{assignment_id}/accept")
@limiter.limit("20/minute")
def accept_delivery(
    request: Request,
    assignment_id: UUID,
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> dict:
    assignment_reference = db.get(DeliveryAssignment, assignment_id)
    if assignment_reference is None:
        raise HTTPException(status_code=409, detail={"code": "delivery_unavailable", "message": "This delivery has already been assigned."})
    fulfillment_reference = db.get(RetailerFulfillment, assignment_reference.fulfillment_id)
    order = db.scalar(
        select(Order).where(Order.id == fulfillment_reference.order_id).with_for_update()
    ) if fulfillment_reference else None
    fulfillment = db.scalar(
        select(RetailerFulfillment)
        .where(RetailerFulfillment.id == assignment_reference.fulfillment_id)
        .with_for_update()
    ) if fulfillment_reference else None
    assignment = db.scalar(
        select(DeliveryAssignment).where(DeliveryAssignment.id == assignment_id).with_for_update()
    )
    agent = db.scalar(select(DeliveryAgent).where(DeliveryAgent.user_id == principal.user.id).with_for_update())
    if agent is None or agent.verification_status != "VERIFIED":
        raise HTTPException(status_code=403, detail={"code": "agent_not_verified", "message": "A verified delivery profile is required."})
    if agent.availability_status != "AVAILABLE":
        raise HTTPException(status_code=409, detail={"code": "agent_offline", "message": "Set your delivery availability to available first."})
    active = db.scalar(
        select(DeliveryAssignment.id).where(
            DeliveryAssignment.agent_id == principal.user.id,
            DeliveryAssignment.status.in_(["ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY"]),
        )
    )
    if active:
        raise HTTPException(status_code=409, detail={"code": "active_delivery", "message": "Complete your active delivery before accepting another."})
    if assignment is None or not is_delivery_assignment_transition_allowed(assignment.status, "ACCEPTED"):
        raise HTTPException(status_code=409, detail={"code": "delivery_unavailable", "message": "This delivery has already been assigned."})
    if fulfillment is None or order is None or fulfillment.status != "READY":
        raise HTTPException(status_code=409, detail={"code": "delivery_not_ready", "message": "This order is not ready for pickup."})
    now = utcnow()
    assignment.agent_id = principal.user.id
    assignment.status = "ACCEPTED"
    assignment.assigned_at = now
    assignment.accepted_at = now
    agent.availability_status = "BUSY"
    db.add(DeliveryEvent(assignment_id=assignment.id, actor_user_id=principal.user.id, previous_status="UNASSIGNED", new_status="ACCEPTED"))
    if order:
        db.add(NotificationOutbox(user_id=order.customer_id, event_type="DELIVERY_ASSIGNED", payload={"order_id": str(order.id), "order_number": order.order_number}))
    db.commit()
    return _delivery_view(db, assignment, reveal_destination=True)


@router.get("/deliveries/me")
def my_deliveries(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> list[dict]:
    assignments = db.scalars(
        select(DeliveryAssignment)
        .where(DeliveryAssignment.agent_id == principal.user.id)
        .order_by(DeliveryAssignment.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [_delivery_view(db, assignment, reveal_destination=True) for assignment in assignments]


@router.post("/deliveries/{assignment_id}/release")
@limiter.limit("20/minute")
def release_my_delivery(
    request: Request,
    assignment_id: UUID,
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> dict:
    """Allow a rider to release an accepted assignment before pickup."""
    assignment = db.scalar(
        select(DeliveryAssignment)
        .where(
            DeliveryAssignment.id == assignment_id,
            DeliveryAssignment.agent_id == principal.user.id,
        )
        .with_for_update()
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail={"code": "delivery_not_found", "message": "Delivery was not found."})
    if assignment.status != "ACCEPTED" or assignment.picked_up_at is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "delivery_release_not_allowed", "message": "Only an accepted delivery that has not been picked up can be released."},
        )

    assignment.status = "UNASSIGNED"
    assignment.agent_id = None
    assignment.accepted_at = None
    agent = db.scalar(
        select(DeliveryAgent).where(DeliveryAgent.user_id == principal.user.id).with_for_update()
    )
    if agent is not None:
        agent.availability_status = "AVAILABLE"
    db.add(
        DeliveryEvent(
            assignment_id=assignment.id,
            actor_user_id=principal.user.id,
            previous_status="ACCEPTED",
            new_status="UNASSIGNED",
            note="Rider released assignment before pickup",
        )
    )
    db.add(
        NotificationOutbox(
            user_id=principal.user.id,
            event_type="DELIVERY_RELEASED",
            payload={"assignment_id": str(assignment.id)},
        )
    )
    dispatch_ready_queue(db)
    db.commit()
    return _delivery_view(db, assignment, reveal_destination=False)


@router.post("/deliveries/{assignment_id}/status")
@limiter.limit("10/minute")
def update_delivery_status(
    assignment_id: UUID,
    payload: DeliveryStatusUpdate,
    request: Request,
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> dict:
    assignment_reference = db.get(DeliveryAssignment, assignment_id)
    if assignment_reference is None or assignment_reference.agent_id != principal.user.id:
        raise HTTPException(status_code=404, detail={"code": "delivery_not_found", "message": "Delivery was not found."})
    fulfillment_reference = db.get(RetailerFulfillment, assignment_reference.fulfillment_id)
    order = db.scalar(
        select(Order).where(Order.id == fulfillment_reference.order_id).with_for_update()
    ) if fulfillment_reference else None
    fulfillment = db.scalar(
        select(RetailerFulfillment)
        .where(RetailerFulfillment.id == assignment_reference.fulfillment_id)
        .with_for_update()
    ) if fulfillment_reference else None
    assignment = db.scalar(
        select(DeliveryAssignment).where(DeliveryAssignment.id == assignment_id).with_for_update()
    )
    agent = db.scalar(select(DeliveryAgent).where(DeliveryAgent.user_id == principal.user.id).with_for_update())
    if assignment is None or assignment.agent_id != principal.user.id:
        raise HTTPException(status_code=404, detail={"code": "delivery_not_found", "message": "Delivery was not found."})
    if agent is None or agent.verification_status != "VERIFIED":
        raise HTTPException(status_code=403, detail={"code": "agent_not_verified", "message": "A verified delivery profile is required."})
    if fulfillment is None or order is None:
        raise HTTPException(status_code=409, detail={"code": "fulfillment_missing", "message": "The order fulfillment record is missing."})
    if not is_delivery_assignment_transition_allowed(assignment.status, payload.status):
        raise HTTPException(status_code=409, detail={"code": "invalid_transition", "message": f"Cannot move a {assignment.status.lower()} delivery to {payload.status.lower()}."})
    if payload.status in {"OUT_FOR_DELIVERY", "DELIVERED"} and not is_fulfillment_transition_allowed(
        fulfillment.status, payload.status
    ):
        raise HTTPException(status_code=409, detail={"code": "invalid_transition", "message": f"Cannot move a {fulfillment.status.lower()} fulfillment to {payload.status.lower()}."})
    if payload.status == "DELIVERED" and assignment.confirmation_code_hash is not None:
        if not payload.confirmation_code or not compare_digest(
            hash_token(payload.confirmation_code),
            assignment.confirmation_code_hash,
        ):
            raise HTTPException(status_code=403, detail={"code": "invalid_delivery_confirmation", "message": "A valid customer confirmation code is required to complete this delivery."})
    previous = assignment.status
    now = utcnow()
    assignment.status = payload.status
    if payload.status == "PICKED_UP":
        assignment.picked_up_at = now
    elif payload.status == "OUT_FOR_DELIVERY":
        fulfillment.status = "OUT_FOR_DELIVERY"
        order.status = "OUT_FOR_DELIVERY"
        db.add(NotificationOutbox(user_id=order.customer_id, event_type="DELIVERY_STARTED", payload={"order_id": str(order.id), "order_number": order.order_number}))
    elif payload.status == "DELIVERED":
        fulfillment.status = "DELIVERED"
        assignment.delivered_at = now
        _consume_fulfillment_inventory(db, fulfillment)
        recompute_order_status(db, order)
        db.add(NotificationOutbox(user_id=order.customer_id, event_type="ORDER_DELIVERED", payload={"order_id": str(order.id), "order_number": order.order_number}))
        # Payments settle online through the provider webhook; a completed
        # delivery never marks a payment successful (cash is out of scope).
        assignment_count = db.scalar(
            select(func.count(DeliveryAssignment.id))
            .join(RetailerFulfillment, RetailerFulfillment.id == DeliveryAssignment.fulfillment_id)
            .where(
                RetailerFulfillment.order_id == order.id,
                DeliveryAssignment.status != "CANCELLED",
            )
        ) or 1
        earning = order.delivery_fee_ugx // assignment_count
        db.add(DeliveryEarning(assignment_id=assignment.id, agent_id=principal.user.id, amount_ugx=earning))
        agent.availability_status = "AVAILABLE"
    db.add(DeliveryEvent(assignment_id=assignment.id, actor_user_id=principal.user.id, previous_status=previous, new_status=payload.status))
    db.commit()
    return _delivery_view(db, assignment, reveal_destination=True)


@router.get("/deliveries/me/history")
def delivery_history(
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> list[dict]:
    assignments = db.scalars(
        select(DeliveryAssignment)
        .where(DeliveryAssignment.agent_id == principal.user.id, DeliveryAssignment.status == "DELIVERED")
        .order_by(DeliveryAssignment.delivered_at.desc())
        .limit(limit)
    ).all()
    return [_delivery_view(db, assignment, reveal_destination=True) for assignment in assignments]


@router.get("/deliveries/me/earnings")
def delivery_earnings(
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.scalars(
        select(DeliveryEarning)
        .where(DeliveryEarning.agent_id == principal.user.id)
        .order_by(DeliveryEarning.created_at.desc())
        .limit(100)
    ).all()
    pending = sum(row.amount_ugx for row in rows if row.status == "PENDING")
    paid = sum(row.amount_ugx for row in rows if row.status == "PAID")
    return {
        "currency": "UGX",
        "owed_by_wewe_ugx": pending,
        "pending_ugx": pending,
        "paid_ugx": paid,
        "payout_status": "AWAITING_SCHEDULED_PAYOUT" if pending else "UP_TO_DATE",
        "entries": [
            {
                "assignment_id": row.assignment_id,
                "amount_ugx": row.amount_ugx,
                "status": row.status,
                "created_at": row.created_at,
                "paid_at": row.paid_at,
                "payout_reference": row.payout_reference,
            }
            for row in rows
        ],
    }


@router.get("/notifications")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(require_roles("CUSTOMER", "RETAILER", "DELIVERY_AGENT", "ADMIN")),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(NotificationOutbox).where(NotificationOutbox.user_id == principal.user.id, NotificationOutbox.channel == "IN_APP")
    if unread_only:
        query = query.where(NotificationOutbox.read_at.is_(None))
    rows = db.scalars(query.order_by(NotificationOutbox.available_at.desc()).limit(limit)).all()
    return [
        {"id": row.id, "event_type": row.event_type, "payload": row.payload, "created_at": row.available_at, "read_at": row.read_at}
        for row in rows
    ]


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_notification_read(
    notification_id: UUID,
    principal: Principal = Depends(require_roles("CUSTOMER", "RETAILER", "DELIVERY_AGENT", "ADMIN")),
    db: Session = Depends(get_db),
) -> None:
    notification = db.scalar(
        select(NotificationOutbox).where(NotificationOutbox.id == notification_id, NotificationOutbox.user_id == principal.user.id)
    )
    if notification is None:
        raise HTTPException(status_code=404, detail={"code": "notification_not_found", "message": "Notification was not found."})
    notification.read_at = notification.read_at or utcnow()
    db.commit()


@router.get("/wishlist")
def get_wishlist(
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.execute(
        select(WishlistItem, Product)
        .join(Product, Product.id == WishlistItem.product_id)
        .where(WishlistItem.customer_id == principal.user.id)
        .order_by(WishlistItem.created_at.desc())
    ).all()
    return [{"product_id": item.product_id, "name": product.name, "category_id": product.category_id, "created_at": item.created_at} for item, product in rows]


@router.post("/wishlist", status_code=status.HTTP_201_CREATED)
def add_wishlist_item(
    payload: WishlistIn,
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> dict:
    product = db.get(Product, payload.product_id)
    if product is None or product.status != "ACTIVE":
        raise HTTPException(status_code=404, detail={"code": "product_not_found", "message": "Product was not found."})
    item = db.get(WishlistItem, (principal.user.id, product.id))
    if item is None:
        item = WishlistItem(customer_id=principal.user.id, product_id=product.id)
        db.add(item)
        db.commit()
    return {"product_id": product.id, "saved": True}


@router.delete("/wishlist/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_wishlist_item(
    product_id: UUID,
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> None:
    item = db.get(WishlistItem, (principal.user.id, product_id))
    if item:
        db.delete(item)
        db.commit()


@router.post("/reviews", status_code=status.HTTP_201_CREATED)
def create_review(
    payload: ReviewCreate,
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> dict:
    item = db.get(OrderItem, payload.order_item_id)
    if item is None or item.product_id is None:
        raise HTTPException(status_code=404, detail={"code": "order_item_not_found", "message": "Purchased item was not found."})
    order = db.get(Order, item.order_id)
    if order is None or order.customer_id != principal.user.id:
        raise HTTPException(status_code=403, detail={"code": "purchase_not_reviewable", "message": "Only delivered purchases can be reviewed."})
    fulfillment_status = db.scalar(
        select(RetailerFulfillment.status).where(
            RetailerFulfillment.order_id == order.id,
            RetailerFulfillment.retailer_id == item.retailer_id,
        )
    )
    if fulfillment_status != "DELIVERED":
        raise HTTPException(status_code=403, detail={"code": "purchase_not_reviewable", "message": "Only delivered purchases can be reviewed."})
    existing = db.scalar(select(Review.id).where(Review.order_item_id == item.id))
    if existing:
        raise HTTPException(status_code=409, detail={"code": "review_exists", "message": "This purchase has already been reviewed."})
    review = Review(
        product_id=item.product_id,
        customer_id=principal.user.id,
        order_item_id=item.id,
        rating=payload.rating,
        body=payload.body,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return {"id": review.id, "product_id": review.product_id, "rating": review.rating, "body": review.body, "created_at": review.created_at}


@router.get("/products/{product_id}/reviews")
def product_reviews(
    product_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = db.execute(
        select(Review, User.name)
        .join(User, User.id == Review.customer_id)
        .where(Review.product_id == product_id, Review.moderation_status == "VISIBLE")
        .order_by(Review.created_at.desc())
        .limit(limit)
    ).all()
    return [{"id": review.id, "rating": review.rating, "body": review.body, "customer_name": name, "created_at": review.created_at} for review, name in rows]
