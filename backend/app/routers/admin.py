from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import Principal, require_roles
from app.models import (
    AuditLog,
    Block,
    Campus,
    Category,
    DeliveryAgent,
    DeliveryAssignment,
    DeliveryEvent,
    DeliveryEarning,
    DeliveryPoint,
    Hall,
    Inventory,
    NotificationOutbox,
    Order,
    OrderItem,
    Payment,
    PaymentEvent,
    PickupPoint,
    PlatformSetting,
    Product,
    RefreshTokenFamily,
    Retailer,
    RetailerFulfillment,
    RetailerFulfillmentEvent,
    Review,
    University,
    User,
    utcnow,
)
from app.routers.commerce import _release_fulfillment_inventory
from app.routers.locations import validate_hierarchy
from app.services.payment_attempts import reserve_refund_attempt, resolve_refund_attempt
from app.schemas import (
    AdminDeliveryAssignment,
    AdminOrderStatusUpdate,
    AdminSettingUpdate,
    BlockCreate,
    CampusCreate,
    CategoryCreate,
    CategoryUpdate,
    DeliveryPayoutIn,
    HallCreate,
    LocationCreate,
    PickupPointCreate,
    PickupPointStatusUpdate,
    ProductModerationUpdate,
    RetailerVerificationUpdate,\n    SettlementCreate,\n    SettlementPayoutUpdate,
    ReviewModerationUpdate,
    RefundConfirmationIn,
    UniversityCreate,
    UserStatusUpdate,
)
from app.services.orders import order_payload
from app.services.retailer_settlement_operations import (\n    RetailerSettlementOperationError,\n    SettlementIdempotencyConflictError,\n    SettlementLifecycleConflictError,\n    create_draft_settlement,\n    list_retailer_settlements,\n    mark_settlement_failed,\n    mark_settlement_review_required,\n    mark_settlement_settled,\n    settlement_snapshot,\n    submit_settlement,\n)\nfrom app.services.state_transitions import (
    aggregate_payment_status,
    is_delivery_assignment_transition_allowed,
    is_fulfillment_transition_allowed,
    is_payment_transition_allowed,
)

router = APIRouter(prefix="/admin", tags=["administration"], dependencies=[Depends(require_roles("ADMIN"))])


def _audit(db: Session, actor: UUID, action: str, resource: str, resource_id: UUID | str, details: dict | None = None) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor,
            action=action,
            resource_type=resource,
            resource_id=str(resource_id),
            details=details or {},
        )
    )


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)) -> dict:
    count = lambda statement: int(db.scalar(statement) or 0)
    totals = {
        "total_users": count(select(func.count(User.id))),
        "active_customers": count(select(func.count(User.id)).where(User.role == "CUSTOMER", User.status == "ACTIVE")),
        "active_retailers": count(select(func.count(Retailer.id)).where(Retailer.status == "ACTIVE", Retailer.verification_status == "VERIFIED")),
        "pending_retailers": count(select(func.count(Retailer.id)).where(Retailer.verification_status == "PENDING")),
        "active_products": count(select(func.count(Product.id)).where(Product.status == "ACTIVE")),
        "orders": count(select(func.count(Order.id))),
        "pending_orders": count(select(func.count(Order.id)).where(Order.status == "PENDING")),
        "deliveries_in_progress": count(select(func.count(DeliveryAssignment.id)).where(DeliveryAssignment.status.in_(["ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY"]))),
        "completed_deliveries": count(select(func.count(DeliveryAssignment.id)).where(DeliveryAssignment.status == "DELIVERED")),
    }
    totals["gross_sales_ugx"] = int(
        db.scalar(select(func.coalesce(func.sum(Order.total_ugx), 0)).where(Order.status == "DELIVERED")) or 0
    )
    return totals


@router.get("/reports/popular-products")
def popular_products(limit: int = Query(default=10, ge=1, le=100), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(OrderItem.product_id, OrderItem.product_name, func.sum(OrderItem.quantity), func.sum(OrderItem.line_total_ugx))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.status == "DELIVERED")
        .group_by(OrderItem.product_id, OrderItem.product_name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(limit)
    ).all()
    return [{"product_id": row[0], "name": row[1], "units_sold": int(row[2]), "sales_ugx": int(row[3])} for row in rows]


@router.get("/reports/popular-categories")
def popular_categories(limit: int = Query(default=10, ge=1, le=100), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(Category.id, Category.name, func.sum(OrderItem.quantity), func.sum(OrderItem.line_total_ugx))
        .join(Product, Product.category_id == Category.id)
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.status == "DELIVERED")
        .group_by(Category.id, Category.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(limit)
    ).all()
    return [{"category_id": row[0], "name": row[1], "units_sold": int(row[2]), "sales_ugx": int(row[3])} for row in rows]


@router.get("/reports/deliveries")
def delivery_performance(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(User.id, User.name, func.count(DeliveryEarning.assignment_id), func.coalesce(func.sum(DeliveryEarning.amount_ugx), 0))
        .join(DeliveryAgent, DeliveryAgent.user_id == User.id)
        .outerjoin(DeliveryEarning, DeliveryEarning.agent_id == User.id)
        .group_by(User.id, User.name)
        .order_by(func.count(DeliveryEarning.assignment_id).desc())
        .limit(limit)
    ).all()
    return [{"agent_user_id": row[0], "name": row[1], "completed_deliveries": int(row[2]), "earnings_ugx": int(row[3])} for row in rows]


@router.post("/delivery-earnings/{assignment_id}/payout")
def mark_delivery_earning_paid(
    assignment_id: UUID,
    payload: DeliveryPayoutIn,
    principal: Principal = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    earning = db.scalar(
        select(DeliveryEarning).where(DeliveryEarning.assignment_id == assignment_id).with_for_update()
    )
    if earning is None:
        raise HTTPException(status_code=404, detail={"code": "earning_not_found", "message": "Delivery earning was not found."})
    if earning.status != "PENDING":
        raise HTTPException(status_code=409, detail={"code": "earning_already_paid", "message": "This earning has already been settled."})
    earning.status = "PAID"
    earning.payout_reference = payload.payout_reference
    earning.paid_at = utcnow()
    _audit(db, principal.user.id, "DELIVERY_EARNING_PAID", "delivery_earning", assignment_id, {"amount_ugx": earning.amount_ugx, "reference": payload.payout_reference})
    db.commit()
    return {"assignment_id": assignment_id, "amount_ugx": earning.amount_ugx, "status": earning.status, "paid_at": earning.paid_at}


@router.get("/reports/order-statuses")
def order_status_statistics(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(Order.status, func.count(Order.id)).group_by(Order.status)).all()
    return {status: int(count) for status, count in rows}


@router.get("/reports/retailers")
def retailer_performance(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(
            Retailer.id,
            Retailer.business_name,
            func.count(func.distinct(case((Order.status == "DELIVERED", OrderItem.order_id)))),
            func.coalesce(func.sum(case((Order.status == "DELIVERED", OrderItem.line_total_ugx), else_=0)), 0),
        )
        .outerjoin(OrderItem, OrderItem.retailer_id == Retailer.id)
        .outerjoin(Order, Order.id == OrderItem.order_id)
        .group_by(Retailer.id, Retailer.business_name)
        .order_by(func.coalesce(func.sum(case((Order.status == "DELIVERED", OrderItem.line_total_ugx), else_=0)), 0).desc())
        .limit(limit)
    ).all()
    return [{"retailer_id": row[0], "business_name": row[1], "orders": int(row[2]), "sales_ugx": int(row[3])} for row in rows]


@router.get("/users")
def list_users(
    role: str | None = None,
    account_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(User)
    if role:
        if role not in {"CUSTOMER", "RETAILER", "DELIVERY_AGENT", "ADMIN"}:
            raise HTTPException(status_code=422, detail={"code": "invalid_role", "message": "Role filter is invalid."})
        query = query.where(User.role == role)
    if account_status:
        if account_status not in {"ACTIVE", "PENDING", "SUSPENDED", "DEACTIVATED"}:
            raise HTTPException(status_code=422, detail={"code": "invalid_status", "message": "Status filter is invalid."})
        query = query.where(User.status == account_status)
    users = db.scalars(query.order_by(User.created_at.desc()).offset(offset).limit(limit)).all()
    return [{"id": row.id, "name": row.name, "email": row.email, "phone": row.phone, "role": row.role, "status": row.status, "created_at": row.created_at} for row in users]


@router.patch("/users/{user_id}/status")
def update_user_status(
    user_id: UUID,
    payload: UserStatusUpdate,
    principal: Principal = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(status_code=404, detail={"code": "user_not_found", "message": "User was not found."})
    if user.id == principal.user.id and payload.status != "ACTIVE":
        raise HTTPException(status_code=409, detail={"code": "cannot_suspend_self", "message": "An administrator cannot suspend their own account."})
    previous = user.status
    user.status = payload.status
    if payload.status != "ACTIVE":
        user.token_version += 1
        for family in db.scalars(select(RefreshTokenFamily).where(RefreshTokenFamily.user_id == user.id, RefreshTokenFamily.revoked_at.is_(None))).all():
            family.revoked_at = utcnow()
    _audit(db, principal.user.id, "USER_STATUS_CHANGED", "user", user.id, {"from": previous, "to": user.status})
    db.commit()
    return {"id": user.id, "status": user.status}


@router.get("/retailers")
def list_retailers(
    verification_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(Retailer)
    if verification_status:
        if verification_status not in {"PENDING", "VERIFIED", "REJECTED"}:
            raise HTTPException(status_code=422, detail={"code": "invalid_status", "message": "Verification status is invalid."})
        query = query.where(Retailer.verification_status == verification_status)
    return [{"id": r.id, "user_id": r.user_id, "business_name": r.business_name, "phone": r.phone, "verification_status": r.verification_status, "status": r.status} for r in db.scalars(query.order_by(Retailer.created_at.desc()).offset(offset).limit(limit)).all()]


@router.patch("/retailers/{retailer_id}/verification")
def verify_retailer(
    retailer_id: UUID,
    payload: RetailerVerificationUpdate,
    principal: Principal = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    retailer = db.scalar(select(Retailer).where(Retailer.id == retailer_id).with_for_update())
    if retailer is None:
        raise HTTPException(status_code=404, detail={"code": "retailer_not_found", "message": "Retailer was not found."})
    previous = retailer.verification_status
    retailer.verification_status = payload.status
    retailer.status = "ACTIVE" if payload.status == "VERIFIED" else retailer.status
    _audit(db, principal.user.id, "RETAILER_VERIFICATION_CHANGED", "retailer", retailer.id, {"from": previous, "to": payload.status, "reason": payload.reason})
    db.add(NotificationOutbox(user_id=retailer.user_id, event_type=f"RETAILER_{payload.status}", payload={"retailer_id": str(retailer.id)}))
    db.commit()
    return {"id": retailer.id, "verification_status": retailer.verification_status, "status": retailer.status}


@router.get("/delivery-agents")
def list_delivery_agents(
    verification_status: str | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(DeliveryAgent, User).join(User, User.id == DeliveryAgent.user_id)
    if verification_status:
        query = query.where(DeliveryAgent.verification_status == verification_status)
    return [{"user_id": agent.user_id, "name": user.name, "phone": agent.phone, "verification_status": agent.verification_status, "availability_status": agent.availability_status} for agent, user in db.execute(query.order_by(User.created_at.desc())).all()]


@router.patch("/delivery-agents/{user_id}/verification")
def verify_delivery_agent(
    user_id: UUID,
    payload: RetailerVerificationUpdate,
    principal: Principal = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    agent = db.scalar(select(DeliveryAgent).where(DeliveryAgent.user_id == user_id).with_for_update())
    if agent is None:
        raise HTTPException(status_code=404, detail={"code": "agent_not_found", "message": "Delivery agent was not found."})
    agent.verification_status = payload.status
    _audit(db, principal.user.id, "AGENT_VERIFICATION_CHANGED", "delivery_agent", user_id, {"to": payload.status, "reason": payload.reason})
    db.commit()
    return {"user_id": user_id, "verification_status": agent.verification_status}


@router.get("/products")
def admin_products(
    product_status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(Product)
    if product_status:
        if product_status not in {"DRAFT", "ACTIVE", "INACTIVE", "REMOVED"}:
            raise HTTPException(status_code=422, detail={"code": "invalid_status", "message": "Product status is invalid."})
        query = query.where(Product.status == product_status)
    rows = db.scalars(query.order_by(Product.created_at.desc()).offset(offset).limit(limit)).all()
    return [{"id": p.id, "category_id": p.category_id, "name": p.name, "status": p.status, "created_at": p.created_at} for p in rows]


@router.patch("/products/{product_id}/moderation")
def moderate_product(
    product_id: UUID,
    payload: ProductModerationUpdate,
    principal: Principal = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    product = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if product is None:
        raise HTTPException(status_code=404, detail={"code": "product_not_found", "message": "Product was not found."})
    previous = product.status
    product.status = payload.status
    _audit(db, principal.user.id, "PRODUCT_MODERATED", "product", product.id, {"from": previous, "to": payload.status})
    db.commit()
    return {"id": product.id, "status": product.status}


@router.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate, principal: Principal = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)) -> dict:
    if payload.parent_id and db.get(Category, payload.parent_id) is None:
        raise HTTPException(status_code=422, detail={"code": "parent_category_not_found", "message": "Parent category was not found."})
    category = Category(**payload.model_dump())
    db.add(category)
    _audit(db, principal.user.id, "CATEGORY_CREATED", "category", payload.slug)
    db.commit()
    db.refresh(category)
    return {"id": category.id, "name": category.name, "slug": category.slug, "parent_id": category.parent_id}


@router.patch("/categories/{category_id}")
def update_category(category_id: UUID, payload: CategoryUpdate, principal: Principal = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)) -> dict:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail={"code": "category_not_found", "message": "Category was not found."})
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(category, key, value)
    _audit(db, principal.user.id, "CATEGORY_UPDATED", "category", category.id, changes)
    db.commit()
    return {"id": category.id, "name": category.name, "slug": category.slug, "is_active": category.is_active}


@router.post("/universities", status_code=status.HTTP_201_CREATED)
def create_university(payload: UniversityCreate, principal: Principal = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)) -> dict:
    university = University(**payload.model_dump())
    db.add(university)
    db.flush()
    _audit(db, principal.user.id, "UNIVERSITY_CREATED", "university", university.id)
    db.commit()
    return {"id": university.id, "name": university.name, "slug": university.slug}


@router.post("/campuses", status_code=status.HTTP_201_CREATED)
def create_campus(payload: CampusCreate, principal: Principal = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)) -> dict:
    if db.get(University, payload.university_id) is None:
        raise HTTPException(status_code=422, detail={"code": "university_not_found", "message": "University was not found."})
    campus = Campus(**payload.model_dump())
    db.add(campus)
    db.flush()
    _audit(db, principal.user.id, "CAMPUS_CREATED", "campus", campus.id)
    db.commit()
    return {"id": campus.id, "name": campus.name, "slug": campus.slug}


@router.post("/halls", status_code=status.HTTP_201_CREATED)
def create_hall(payload: HallCreate, principal: Principal = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)) -> dict:
    if db.get(Campus, payload.campus_id) is None:
        raise HTTPException(status_code=422, detail={"code": "campus_not_found", "message": "Campus was not found."})
    hall = Hall(**payload.model_dump())
    db.add(hall)
    db.flush()
    _audit(db, principal.user.id, "HALL_CREATED", "hall", hall.id)
    db.commit()
    return {"id": hall.id, "campus_id": hall.campus_id, "name": hall.name, "kind": hall.kind}


@router.post("/blocks", status_code=status.HTTP_201_CREATED)
def create_block(payload: BlockCreate, principal: Principal = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)) -> dict:
    if db.get(Hall, payload.hall_id) is None:
        raise HTTPException(status_code=422, detail={"code": "hall_not_found", "message": "Hall was not found."})
    block = Block(**payload.model_dump())
    db.add(block)
    db.flush()
    _audit(db, principal.user.id, "BLOCK_CREATED", "block", block.id)
    db.commit()
    return {"id": block.id, "hall_id": block.hall_id, "name": block.name}


@router.post("/delivery-points", status_code=status.HTTP_201_CREATED)
def create_delivery_point(payload: LocationCreate, principal: Principal = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)) -> dict:
    if payload.is_private:
        raise HTTPException(status_code=422, detail={"code": "private_location_not_allowed", "message": "Admin-managed campus points must be public."})
    if payload.kind == "ROOM":
        raise HTTPException(status_code=422, detail={"code": "private_location_required", "message": "Room-level locations must be owned by a customer."})
    validate_hierarchy(db, payload)
    point = DeliveryPoint(**payload.model_dump(), owner_user_id=None)
    db.add(point)
    db.flush()
    _audit(db, principal.user.id, "DELIVERY_POINT_CREATED", "delivery_point", point.id)
    db.commit()
    return {"id": point.id, "campus_id": point.campus_id, "name": point.name, "kind": point.kind}


@router.post("/pickup-points", status_code=status.HTTP_201_CREATED)
def create_pickup_point(payload: PickupPointCreate, principal: Principal = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)) -> dict:
    location_data = LocationCreate(campus_id=payload.campus_id, hall_id=payload.hall_id, kind="PICKUP_POINT", name=payload.name, directions=payload.directions, latitude=payload.latitude, longitude=payload.longitude)
    validate_hierarchy(db, location_data)
    point = DeliveryPoint(campus_id=payload.campus_id, hall_id=payload.hall_id, kind="PICKUP_POINT", name=payload.name, directions=payload.directions, latitude=payload.latitude, longitude=payload.longitude, is_private=False)
    db.add(point)
    db.flush()
    pickup = PickupPoint(delivery_point_id=point.id, contact_name=payload.contact_name, contact_phone=payload.contact_phone, opening_hours=payload.opening_hours)
    db.add(pickup)
    _audit(db, principal.user.id, "PICKUP_POINT_CREATED", "pickup_point", point.id)
    db.commit()
    return {"delivery_point_id": point.id, "name": point.name, "operating_status": pickup.operating_status}


@router.get("/pickup-points")
def list_pickup_points(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(PickupPoint, DeliveryPoint).join(DeliveryPoint, DeliveryPoint.id == PickupPoint.delivery_point_id).order_by(DeliveryPoint.name)).all()
    return [{"id": pickup.delivery_point_id, "campus_id": point.campus_id, "name": point.name, "contact_name": pickup.contact_name, "contact_phone": pickup.contact_phone, "opening_hours": pickup.opening_hours, "operating_status": pickup.operating_status} for pickup, point in rows]


@router.patch("/pickup-points/{point_id}/status")
def update_pickup_status(point_id: UUID, payload: PickupPointStatusUpdate, principal: Principal = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)) -> dict:
    pickup = db.scalar(select(PickupPoint).where(PickupPoint.delivery_point_id == point_id).with_for_update())
    if pickup is None:
        raise HTTPException(status_code=404, detail={"code": "pickup_point_not_found", "message": "Pickup point was not found."})
    previous = pickup.operating_status
    pickup.operating_status = payload.operating_status
    _audit(db, principal.user.id, "PICKUP_POINT_STATUS_CHANGED", "pickup_point", point_id, {"from": previous, "to": pickup.operating_status})
    db.commit()
    return {"delivery_point_id": point_id, "operating_status": pickup.operating_status}


@router.post("/deliveries/{assignment_id}/assign")
def assign_delivery(assignment_id: UUID, payload: AdminDeliveryAssignment, principal: Principal = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)) -> dict:
    assignment_reference = db.get(DeliveryAssignment, assignment_id)
    if assignment_reference is None:
        raise HTTPException(status_code=409, detail={"code": "delivery_unavailable", "message": "Delivery cannot be assigned in its current state."})
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
    agent = db.scalar(select(DeliveryAgent).where(DeliveryAgent.user_id == payload.agent_user_id).with_for_update())
    if assignment is None or assignment.status != "UNASSIGNED":
        raise HTTPException(status_code=409, detail={"code": "delivery_unavailable", "message": "Delivery cannot be assigned in its current state."})
    if fulfillment is None or fulfillment.status != "READY":
        raise HTTPException(status_code=409, detail={"code": "delivery_not_ready", "message": "The retailer must mark the order ready before dispatch."})
    if not is_delivery_assignment_transition_allowed(assignment.status, "ACCEPTED"):
        raise HTTPException(status_code=409, detail={"code": "delivery_unavailable", "message": "Delivery cannot be assigned in its current state."})
    if agent is None or agent.verification_status != "VERIFIED" or agent.availability_status != "AVAILABLE":
        raise HTTPException(status_code=409, detail={"code": "agent_unavailable", "message": "Choose a verified, available delivery agent."})
    agent_user = db.get(User, agent.user_id)
    if agent_user is None or agent_user.status != "ACTIVE":
        raise HTTPException(status_code=409, detail={"code": "agent_unavailable", "message": "Choose an active delivery agent."})
    active = db.scalar(select(DeliveryAssignment.id).where(DeliveryAssignment.agent_id == agent.user_id, DeliveryAssignment.status.in_(["ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY"])))
    if active:
        raise HTTPException(status_code=409, detail={"code": "agent_busy", "message": "Delivery agent already has an active assignment."})
    previous = assignment.status
    assignment.agent_id = agent.user_id
    assignment.status = "ACCEPTED"
    assignment.assigned_at = utcnow()
    assignment.accepted_at = utcnow()
    agent.availability_status = "BUSY"
    db.add(DeliveryEvent(assignment_id=assignment.id, actor_user_id=principal.user.id, previous_status=previous, new_status="ACCEPTED", note="Assigned by administrator"))
    _audit(db, principal.user.id, "DELIVERY_ASSIGNED", "delivery", assignment.id, {"agent_user_id": str(agent.user_id)})
    if order:
        db.add(NotificationOutbox(user_id=order.customer_id, event_type="DELIVERY_ASSIGNED", payload={"order_id": str(order.id), "order_number": order.order_number}))
    db.commit()
    return {"id": assignment.id, "agent_user_id": agent.user_id, "status": assignment.status}


@router.get("/orders")
def admin_orders(status_filter: str | None = None, limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)) -> list[dict]:
    query = select(Order)
    if status_filter:
        query = query.where(Order.status == status_filter)
    orders = db.scalars(query.order_by(Order.created_at.desc()).offset(offset).limit(limit)).all()
    return [order_payload(db, order) for order in orders]


@router.post("/payments/{payment_id}/confirm-refund")
def confirm_external_refund(
    payment_id: UUID,
    payload: RefundConfirmationIn,
    principal: Principal = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    payment_reference = db.get(Payment, payment_id)
    if payment_reference is None:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Payment was not found."})
    order = db.scalar(select(Order).where(Order.id == payment_reference.order_id).with_for_update())
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if payment is None:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found", "message": "Payment was not found."})
    event_id = f"admin-refund:{payload.provider_event_id}"
    existing_event = db.scalar(select(PaymentEvent).where(PaymentEvent.provider_event_id == event_id))
    if existing_event:
        if existing_event.payment_id == payment.id and existing_event.status == "REFUNDED":
            return {"payment_id": payment.id, "status": payment.status, "amount_ugx": payment.amount_ugx, "duplicate": True}
        raise HTTPException(status_code=409, detail={"code": "refund_already_recorded", "message": "That refund reference has already been recorded."})
    if payment.status != "SUCCESSFUL":
        raise HTTPException(status_code=409, detail={"code": "payment_not_refundable", "message": "Only a successful payment can be marked refunded."})
    if not is_payment_transition_allowed(payment.status, "REFUNDED"):
        raise HTTPException(status_code=409, detail={"code": "payment_not_refundable", "message": "Only a successful payment can be marked refunded."})
    refund = reserve_refund_attempt(
        db,
        payment.id,
        amount_ugx=payment.amount_ugx,
        idempotency_key=event_id,
        external_reference=payload.provider_event_id,
    )
    resolve_refund_attempt(
        db,
        refund.id,
        outcome="CONFIRMED",
        evidence={"source": "admin_confirmation", "provider_event_id": payload.provider_event_id},
    )
    if order:
        db.flush()
        order.payment_status = aggregate_payment_status(
            db.scalars(select(Payment.status).where(Payment.order_id == order.id)).all()
        )
        db.add(NotificationOutbox(user_id=payment.customer_id, event_type="PAYMENT_REFUNDED", payload={"order_id": str(order.id), "order_number": order.order_number}))
    db.add(PaymentEvent(payment_id=payment.id, provider_event_id=event_id, status="REFUNDED"))
    _audit(db, principal.user.id, "PAYMENT_REFUND_CONFIRMED", "payment", payment.id, {"provider_event_id": payload.provider_event_id, "amount_ugx": payment.amount_ugx})
    db.commit()
    return {"payment_id": payment.id, "status": payment.status, "amount_ugx": payment.amount_ugx}


@router.patch("/orders/{order_id}/status")
def override_order_status(order_id: UUID, payload: AdminOrderStatusUpdate, principal: Principal = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)) -> dict:
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise HTTPException(status_code=404, detail={"code": "order_not_found", "message": "Order was not found."})
    if order.status in {"DELIVERED", "PARTIALLY_DELIVERED", "CANCELLED", "REJECTED"}:
        raise HTTPException(status_code=409, detail={"code": "terminal_order", "message": "A completed or cancelled order cannot be overridden."})
    if order.payment_status == "PAID":
        raise HTTPException(status_code=409, detail={"code": "refund_required", "message": "Refund the successful payment before cancelling this order."})
    pending_mobile_payment = db.scalar(
        select(Payment.id).where(
            Payment.order_id == order.id,
            Payment.status == "PENDING",
            Payment.method != "CASH",
        )
    )
    if pending_mobile_payment:
        raise HTTPException(status_code=409, detail={"code": "payment_resolution_required", "message": "Resolve the pending mobile-money payment before changing this order."})
    previous = order.status
    fulfillments = db.scalars(
        select(RetailerFulfillment)
        .where(RetailerFulfillment.order_id == order.id)
        .order_by(RetailerFulfillment.id)
        .with_for_update()
    ).all()
    fulfillment_ids = [fulfillment.id for fulfillment in fulfillments]
    assignments = db.scalars(
        select(DeliveryAssignment)
        .where(DeliveryAssignment.fulfillment_id.in_(fulfillment_ids))
        .order_by(DeliveryAssignment.id)
        .with_for_update()
    ).all() if fulfillment_ids else []
    if any(
        assignment.status in {"PICKED_UP", "OUT_FOR_DELIVERY", "DELIVERED"}
        or assignment.picked_up_at is not None
        or assignment.status == "ACCEPTED"
        for assignment in assignments
    ):
        raise HTTPException(status_code=409, detail={"code": "delivery_in_progress", "message": "A rider must resolve active deliveries before this order can be overridden."})
    if any(
        assignment.status != "CANCELLED"
        and not is_delivery_assignment_transition_allowed(assignment.status, "CANCELLED")
        for assignment in assignments
    ):
        raise HTTPException(status_code=409, detail={"code": "delivery_in_progress", "message": "A rider must resolve active deliveries before this order can be overridden."})
    target_fulfillment_status = "CANCELLED" if payload.status == "CANCELLED" else "REJECTED"
    if payload.status == "CANCELLED" and any(
        fulfillment.status not in {"REJECTED", "CANCELLED"}
        and not is_fulfillment_transition_allowed(fulfillment.status, target_fulfillment_status)
        for fulfillment in fulfillments
    ):
        raise HTTPException(status_code=409, detail={"code": "fulfillment_state_conflict", "message": "A fulfillment cannot be changed in its current state."})
    agent_ids = sorted({assignment.agent_id for assignment in assignments if assignment.agent_id is not None})
    agents = {
        agent.user_id: agent
        for agent in db.scalars(
            select(DeliveryAgent)
            .where(DeliveryAgent.user_id.in_(agent_ids))
            .order_by(DeliveryAgent.user_id)
            .with_for_update()
        ).all()
    } if agent_ids else {}
    for fulfillment in fulfillments:
        if fulfillment.status in {"REJECTED", "CANCELLED"}:
            continue
        previous = fulfillment.status
        _release_fulfillment_inventory(db, fulfillment.id)
        fulfillment.status = target_fulfillment_status
        db.add(RetailerFulfillmentEvent(fulfillment_id=fulfillment.id, actor_user_id=principal.user.id, previous_status=previous, new_status=fulfillment.status, note=payload.reason))
    for assignment in assignments:
        if assignment.status == "CANCELLED":
            continue
        previous = assignment.status
        assignment.status = "CANCELLED"
        db.add(DeliveryEvent(assignment_id=assignment.id, actor_user_id=principal.user.id, previous_status=previous, new_status="CANCELLED", note="Cancelled by administrator"))
    db.flush()
    for agent_id, agent in agents.items():
        if agent.availability_status == "BUSY" and not db.scalar(
            select(DeliveryAssignment.id).where(
                DeliveryAssignment.agent_id == agent_id,
                DeliveryAssignment.status.in_(["ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY"]),
            )
        ):
            agent.availability_status = "AVAILABLE"
    order.status = payload.status
    order.cancelled_at = utcnow() if payload.status == "CANCELLED" else order.cancelled_at
    cash_payments = db.scalars(
        select(Payment).where(
            Payment.order_id == order.id,
            Payment.method == "CASH",
            Payment.status == "PENDING",
        )
    ).all()
    for payment in cash_payments:
        payment.status = "FAILED"
    if cash_payments:
        db.flush()
        order.payment_status = aggregate_payment_status(
            db.scalars(select(Payment.status).where(Payment.order_id == order.id)).all()
        )
    _audit(db, principal.user.id, "ORDER_STATUS_OVERRIDDEN", "order", order.id, {"from": previous, "to": payload.status, "reason": payload.reason})
    db.add(NotificationOutbox(user_id=order.customer_id, event_type=f"ORDER_{payload.status}", payload={"order_id": str(order.id), "reason": payload.reason}))
    db.commit()
    return {"id": order.id, "order_number": order.order_number, "status": order.status}


@router.patch("/reviews/{review_id}/moderation")
def moderate_review(review_id: UUID, payload: ReviewModerationUpdate, principal: Principal = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)) -> dict:
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail={"code": "review_not_found", "message": "Review was not found."})
    previous = review.moderation_status
    review.moderation_status = payload.status
    _audit(db, principal.user.id, "REVIEW_MODERATED", "review", review.id, {"from": previous, "to": payload.status})
    db.commit()
    return {"id": review.id, "moderation_status": review.moderation_status}


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> dict:
    return {setting.key: setting.value for setting in db.scalars(select(PlatformSetting).order_by(PlatformSetting.key)).all()}


@router.put("/settings/{key}")
def update_setting(key: str, payload: AdminSettingUpdate, principal: Principal = Depends(require_roles("ADMIN")), db: Session = Depends(get_db)) -> dict:
    if key not in {"delivery_fee_ugx"}:
        raise HTTPException(status_code=404, detail={"code": "setting_not_found", "message": "Setting is not editable through this endpoint."})
    if "amount" not in payload.value or isinstance(payload.value["amount"], bool) or not isinstance(payload.value["amount"], int) or not 0 <= payload.value["amount"] <= 100_000:
        raise HTTPException(status_code=422, detail={"code": "invalid_setting", "message": "Delivery fee amount must be an integer from 0 to 100000 UGX."})
    setting = db.get(PlatformSetting, key)
    if setting is None:
        setting = PlatformSetting(key=key, value=payload.value, updated_by=principal.user.id)
        db.add(setting)
    else:
        setting.value = payload.value
        setting.updated_by = principal.user.id
    _audit(db, principal.user.id, "PLATFORM_SETTING_CHANGED", "platform_setting", key, payload.value)
    db.commit()
    return {"key": key, "value": payload.value}


@router.get("/audit-logs")
def audit_logs(limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)).all()
    return [{"id": row.id, "actor_user_id": row.actor_user_id, "action": row.action, "resource_type": row.resource_type, "resource_id": row.resource_id, "details": row.details, "created_at": row.created_at} for row in rows]
