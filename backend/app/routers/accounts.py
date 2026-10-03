import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import Principal, require_roles
from app.models import (
    CustomerProfile,
    DeliveryAgent,
    DeliveryAssignment,
    DeliveryPoint,
    Product,
    Retailer,
    RetailerProduct,
    User,
)
from app.schemas import CustomerProfileUpdate, DeliveryAgentProfileUpdate, RetailerAvailabilityUpdate, RetailerProfileUpdate

router = APIRouter(tags=["profiles", "retailers"])


def _validate_phone(phone: str) -> str:
    normalized = phone.replace(" ", "").replace("-", "")
    if not normalized.startswith("+") or not normalized[1:].isdigit() or not 8 <= len(normalized[1:]) <= 15:
        raise HTTPException(status_code=422, detail={"code": "invalid_phone", "message": "Phone must use international format, for example +2567XXXXXXXX."})
    return normalized


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:180] or "retailer"


@router.get("/users/me/profile")
def get_customer_profile(
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> dict:
    profile = db.get(CustomerProfile, principal.user.id)
    return {
        "user_id": principal.user.id,
        "preferred_delivery_point_id": profile.preferred_delivery_point_id if profile else None,
        "marketing_opt_in": profile.marketing_opt_in if profile else False,
    }


@router.patch("/users/me/profile")
def update_customer_profile(
    payload: CustomerProfileUpdate,
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> dict:
    profile = db.get(CustomerProfile, principal.user.id)
    if profile is None:
        profile = CustomerProfile(user_id=principal.user.id)
        db.add(profile)
    changes = payload.model_dump(exclude_unset=True)
    if "preferred_delivery_point_id" in changes and changes["preferred_delivery_point_id"] is not None:
        point = db.get(DeliveryPoint, changes["preferred_delivery_point_id"])
        if point is None or not point.is_active or (point.is_private and point.owner_user_id != principal.user.id):
            raise HTTPException(status_code=404, detail={"code": "delivery_point_not_found", "message": "Delivery point was not found."})
    for key, value in changes.items():
        setattr(profile, key, value)
    db.commit()
    return {
        "user_id": principal.user.id,
        "preferred_delivery_point_id": profile.preferred_delivery_point_id,
        "marketing_opt_in": profile.marketing_opt_in,
    }


@router.get("/retailers")
def list_public_retailers(
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[dict]:
    query = (
        select(Retailer)
        .join(User, User.id == Retailer.user_id)
        .where(Retailer.status == "ACTIVE", Retailer.verification_status == "VERIFIED", User.status == "ACTIVE")
    )
    if q:
        query = query.where(Retailer.business_name.ilike(f"%{q[:120]}%"))
    retailers = db.scalars(query.order_by(Retailer.business_name).offset(max(offset, 0)).limit(min(max(limit, 1), 100))).all()
    retailer_ids = [retailer.id for retailer in retailers]
    product_counts: dict[UUID, int] = {}
    if retailer_ids:
        product_counts = dict(
            db.execute(
                select(RetailerProduct.retailer_id, func.count(RetailerProduct.id))
                .join(Product, Product.id == RetailerProduct.product_id)
                .where(
                    RetailerProduct.retailer_id.in_(retailer_ids),
                    RetailerProduct.is_active.is_(True),
                    Product.status == "ACTIVE",
                )
                .group_by(RetailerProduct.retailer_id)
            ).all()
        )
    return [
        {
            "id": retailer.id,
            "business_name": retailer.business_name,
            "slug": retailer.slug,
            "description": retailer.description,
            "product_count": product_counts.get(retailer.id, 0),
        }
        for retailer in retailers
    ]


@router.get("/retailers/me")
def get_retailer_profile(
    principal: Principal = Depends(require_roles("RETAILER")),
    db: Session = Depends(get_db),
) -> dict:
    retailer = db.scalar(select(Retailer).where(Retailer.user_id == principal.user.id))
    if retailer is None:
        raise HTTPException(status_code=404, detail={"code": "retailer_profile_missing", "message": "Retailer profile was not found."})
    location = db.get(DeliveryPoint, retailer.location_id) if retailer.location_id else None
    return {
        "id": retailer.id,
        "business_name": retailer.business_name,
        "slug": retailer.slug,
        "description": retailer.description,
        "phone": retailer.phone,
        "location_id": retailer.location_id,
        "location": {
            "id": location.id,
            "name": location.name,
            "directions": location.directions,
            "latitude": float(location.latitude) if location and location.latitude is not None else None,
            "longitude": float(location.longitude) if location and location.longitude is not None else None,
            "is_private": location.is_private,
        } if location else None,
        "verification_status": retailer.verification_status,
        "status": retailer.status,
    }


@router.patch("/retailers/me")
def update_retailer_profile(
    payload: RetailerProfileUpdate,
    principal: Principal = Depends(require_roles("RETAILER")),
    db: Session = Depends(get_db),
) -> dict:
    retailer = db.scalar(select(Retailer).where(Retailer.user_id == principal.user.id).with_for_update())
    if retailer is None:
        raise HTTPException(status_code=404, detail={"code": "retailer_profile_missing", "message": "Retailer profile was not found."})
    changes = payload.model_dump(exclude_unset=True)
    if "location_id" in changes:
        location_id = changes["location_id"]
        if location_id is None:
            raise HTTPException(status_code=422, detail={"code": "pickup_location_required", "message": "A pickup location is required for every retailer."})
        point = db.get(DeliveryPoint, location_id)
        if (
            point is None
            or not point.is_active
            or point.kind == "ROOM"
            or (point.is_private and point.owner_user_id != principal.user.id)
        ):
            raise HTTPException(status_code=422, detail={"code": "invalid_location", "message": "Choose an active campus pickup location or create your own retailer pickup point."})
    if changes.get("phone") is not None:
        changes["phone"] = _validate_phone(changes["phone"])
    if changes.get("business_name"):
        name = changes["business_name"].strip()
        slug = _slug(name)
        collision = db.scalar(select(Retailer.id).where(Retailer.slug == slug, Retailer.id != retailer.id))
        if collision:
            slug = f"{slug}-{str(retailer.id)[:8]}"
        retailer.slug = slug
        changes["business_name"] = name
    for key, value in changes.items():
        setattr(retailer, key, value)
    db.commit()
    return {"id": retailer.id, "business_name": retailer.business_name, "slug": retailer.slug, "description": retailer.description, "phone": retailer.phone, "location_id": retailer.location_id, "verification_status": retailer.verification_status, "status": retailer.status}


@router.post("/retailers/me/pickup-location", response_model=DeliveryPoint, status_code=201)
def create_retailer_pickup_location(
    payload: LocationCreate,
    principal: Principal = Depends(require_roles("RETAILER")),
    db: Session = Depends(get_db),
) -> DeliveryPoint:
    """Create an exact retailer-owned pickup point and assign it to the store."""
    if payload.kind == "ROOM":
        raise HTTPException(status_code=422, detail={"code": "invalid_pickup_location_type", "message": "Retailers cannot use a room as a pickup location."})
    if payload.latitude is None or payload.longitude is None:
        raise HTTPException(status_code=422, detail={"code": "pickup_coordinates_required", "message": "Provide the pickup location coordinates so WEWE can calculate road delivery fees."})
    from app.routers.locations import validate_hierarchy
    validate_hierarchy(db, payload)
    retailer = db.scalar(select(Retailer).where(Retailer.user_id == principal.user.id).with_for_update())
    if retailer is None:
        raise HTTPException(status_code=404, detail={"code": "retailer_profile_missing", "message": "Retailer profile was not found."})
    previous = db.get(DeliveryPoint, retailer.location_id) if retailer.location_id else None
    point = DeliveryPoint(
        campus_id=payload.campus_id,
        hall_id=payload.hall_id,
        block_id=payload.block_id,
        owner_user_id=principal.user.id,
        kind="PICKUP_POINT",
        name=payload.name.strip(),
        directions=payload.directions,
        latitude=payload.latitude,
        longitude=payload.longitude,
        google_place_id=payload.google_place_id,
        is_private=True,
    )
    db.add(point)
    db.flush()
    retailer.location_id = point.id
    if previous is not None and previous.owner_user_id == principal.user.id and previous.id != point.id:
        previous.is_active = False
    db.commit()
    db.refresh(point)
    return point


@router.patch("/retailers/me/availability")
def update_retailer_availability(
    payload: RetailerAvailabilityUpdate,
    principal: Principal = Depends(require_roles("RETAILER")),
    db: Session = Depends(get_db),
) -> dict:
    retailer = db.scalar(select(Retailer).where(Retailer.user_id == principal.user.id).with_for_update())
    if retailer is None:
        raise HTTPException(status_code=404, detail={"code": "retailer_profile_missing", "message": "Retailer profile was not found."})
    if payload.is_open and retailer.verification_status != "VERIFIED":
        raise HTTPException(status_code=403, detail={"code": "retailer_not_verified", "message": "Only verified retailers can open their shop."})
    if payload.is_open and retailer.location_id is None:
        raise HTTPException(status_code=409, detail={"code": "pickup_location_required", "message": "Set your pickup location before opening your shop."})
    retailer.status = "ACTIVE" if payload.is_open else "INACTIVE"
    db.commit()
    return {"is_open": retailer.status == "ACTIVE"}


@router.get("/retailers/{slug}")
def get_public_retailer(slug: str, db: Session = Depends(get_db)) -> dict:
    retailer = db.scalar(
        select(Retailer)
        .join(User, User.id == Retailer.user_id)
        .where(Retailer.slug == slug, Retailer.status == "ACTIVE", Retailer.verification_status == "VERIFIED", User.status == "ACTIVE")
    )
    if retailer is None:
        raise HTTPException(status_code=404, detail={"code": "retailer_not_found", "message": "Retailer was not found."})
    listings = db.execute(
        select(RetailerProduct, Product)
        .join(Product, Product.id == RetailerProduct.product_id)
        .where(RetailerProduct.retailer_id == retailer.id, RetailerProduct.is_active.is_(True), Product.status == "ACTIVE")
        .order_by(Product.name)
    ).all()
    return {
        "id": retailer.id,
        "business_name": retailer.business_name,
        "slug": retailer.slug,
        "description": retailer.description,
        "products": [{"id": product.id, "name": product.name, "retailer_product_id": listing.id, "price_ugx": listing.price_ugx} for listing, product in listings],
    }


@router.get("/deliveries/me/profile")
def get_delivery_profile(
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> dict:
    agent = db.get(DeliveryAgent, principal.user.id)
    if agent is None:
        raise HTTPException(status_code=404, detail={"code": "agent_profile_missing", "message": "Delivery profile was not found."})
    return {"user_id": agent.user_id, "phone": agent.phone, "verification_status": agent.verification_status, "availability_status": agent.availability_status, "transport_mode": agent.transport_mode}


@router.patch("/deliveries/me/profile")
def update_delivery_profile(
    payload: DeliveryAgentProfileUpdate,
    principal: Principal = Depends(require_roles("DELIVERY_AGENT")),
    db: Session = Depends(get_db),
) -> dict:
    agent = db.scalar(select(DeliveryAgent).where(DeliveryAgent.user_id == principal.user.id).with_for_update())
    if agent is None:
        raise HTTPException(status_code=404, detail={"code": "agent_profile_missing", "message": "Delivery profile was not found."})
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("phone") is not None:
        phone = _validate_phone(changes["phone"])
        if phone != agent.phone:
            active_delivery = db.scalar(
                select(DeliveryAssignment.id).where(
                    DeliveryAssignment.agent_id == principal.user.id,
                    DeliveryAssignment.status.in_(["ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY"]),
                )
            )
            if active_delivery:
                raise HTTPException(status_code=409, detail={"code": "active_delivery", "message": "Complete your active delivery before changing your phone number."})
            agent.phone = phone
            agent.verification_status = "PENDING"
            agent.availability_status = "OFFLINE"
    if "transport_mode" in changes:
        agent.transport_mode = changes["transport_mode"]
    db.commit()
    return {"user_id": agent.user_id, "phone": agent.phone, "verification_status": agent.verification_status, "availability_status": agent.availability_status, "transport_mode": agent.transport_mode}
