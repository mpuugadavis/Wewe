from datetime import datetime, timezone
import logging
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.dependencies import Principal, require_roles
from app.limiter import limiter
from app.models import (
    Cart,
    CartItem,
    DeliveryAssignment,
    DeliveryEvent,
    Inventory,
    NotificationOutbox,
    Order,
    OrderItem,
    Payment,
    PlatformSetting,
    Product,
    Retailer,
    RetailerFulfillment,
    RetailerFulfillmentEvent,
    RetailerProduct,
    User,
    utcnow,
)
from app.schemas import CartItemIn, CartItemUpdate, CheckoutIn, FulfillmentAction, OrderOut, PaymentCreate, PaymentOut
from app.services.delivery_dispatch import dispatch_ready_fulfillment
from app.services.delivery_pricing import remove_committed_delivery_quote
from app.services.orders import create_order, order_payload, preview_checkout_quote, recompute_order_status
from app.services.payment_attempts import record_reconciliation_unresolved, reserve_refund_attempt
from app.services.flutterwave_adapter import FlutterwaveAPIError
from app.services.payments import PaymentProviderUnavailable, PaymentRequest, payment_providers
from app.services.state_transitions import (
    aggregate_payment_status,
    is_delivery_assignment_transition_allowed,
    is_fulfillment_transition_allowed,
)

router = APIRouter(tags=["commerce"])
logger = logging.getLogger(__name__)


def _get_cart(db: Session, customer_id: UUID, create: bool = False) -> Cart | None:
    cart = db.scalar(select(Cart).where(Cart.customer_id == customer_id).with_for_update())
    if cart is None and create:
        cart = Cart(customer_id=customer_id)
        db.add(cart)
        db.flush()
    return cart


def _cart_payload(db: Session, cart: Cart | None) -> dict:
    if cart is None:
        return {"id": None, "currency": "UGX", "items": [], "subtotal_ugx": 0}
    rows = db.execute(
        select(CartItem, RetailerProduct, Product, Retailer, Inventory)
        .join(RetailerProduct, RetailerProduct.id == CartItem.retailer_product_id)
        .join(Product, Product.id == RetailerProduct.product_id)
        .join(Retailer, Retailer.id == RetailerProduct.retailer_id)
        .outerjoin(Inventory, Inventory.retailer_product_id == RetailerProduct.id)
        .where(CartItem.cart_id == cart.id)
        .order_by(CartItem.created_at)
    ).all()
    items = []
    for item, listing, product, retailer, inventory in rows:
        items.append(
            {
                "id": item.id,
                "retailer_product_id": listing.id,
                "product_id": product.id,
                "product_name": product.name,
                "retailer_name": retailer.business_name,
                "image_url": db.scalar(select_from_product_image(product.id)),
                "unit_price_ugx": listing.price_ugx,
                "quantity": item.quantity,
                "line_total_ugx": listing.price_ugx * item.quantity,
                "stock_available": max(0, inventory.quantity - inventory.reserved_quantity) if inventory else 0,
            }
        )
    return {
        "id": cart.id,
        "currency": "UGX",
        "items": items,
        "subtotal_ugx": sum(line["line_total_ugx"] for line in items),
    }


def select_from_product_image(product_id: UUID):
    from app.models import ProductImage

    return select(ProductImage.url).where(ProductImage.product_id == product_id).order_by(ProductImage.sort_order).limit(1)


def _get_customer_listing(db: Session, listing_id: UUID, lock: bool = False):
    statement = select(RetailerProduct).where(RetailerProduct.id == listing_id)
    if lock:
        statement = statement.with_for_update()
    listing = db.scalar(statement)
    if listing is None:
        return None
    product = db.get(Product, listing.product_id)
    retailer = db.get(Retailer, listing.retailer_id)
    retailer_user = db.get(User, retailer.user_id) if retailer else None
    inventory_query = select(Inventory).where(Inventory.retailer_product_id == listing.id)
    if lock:
        inventory_query = inventory_query.with_for_update()
    inventory = db.scalar(inventory_query)
    if product is None or retailer is None or retailer_user is None:
        return None
    return listing, product, retailer, retailer_user, inventory


@router.get("/cart")
def get_cart(
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> dict:
    return _cart_payload(db, _get_cart(db, principal.user.id))


@router.post("/cart/items", status_code=status.HTTP_200_OK)
def add_cart_item(
    payload: CartItemIn,
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> dict:
    result = _get_customer_listing(db, payload.retailer_product_id, lock=True)
    if result is None:
        raise HTTPException(status_code=404, detail={"code": "listing_not_found", "message": "Product listing was not found."})
    listing, product, retailer, retailer_user, inventory = result
    if (
        not listing.is_active
        or product.status != "ACTIVE"
        or retailer.status != "ACTIVE"
        or retailer.verification_status != "VERIFIED"
        or retailer_user.status != "ACTIVE"
        or inventory is None
    ):
        raise HTTPException(status_code=409, detail={"code": "listing_unavailable", "message": "This product is not currently available."})
    cart = _get_cart(db, principal.user.id, create=True)
    item = db.scalar(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.retailer_product_id == listing.id).with_for_update()
    )
    quantity = (item.quantity if item else 0) + payload.quantity
    available = inventory.quantity - inventory.reserved_quantity
    if quantity > available:
        raise HTTPException(status_code=409, detail={"code": "insufficient_stock", "message": f"Only {available} are currently available."})
    if item:
        item.quantity = quantity
    else:
        db.add(CartItem(cart_id=cart.id, retailer_product_id=listing.id, quantity=quantity))
    db.commit()
    return _cart_payload(db, _get_cart(db, principal.user.id))


@router.patch("/cart/items/{item_id}")
def update_cart_item(
    item_id: UUID,
    payload: CartItemUpdate,
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> dict:
    item = db.scalar(
        select(CartItem)
        .join(Cart, Cart.id == CartItem.cart_id)
        .where(CartItem.id == item_id, Cart.customer_id == principal.user.id)
        .with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "cart_item_not_found", "message": "Cart item was not found."})
    result = _get_customer_listing(db, item.retailer_product_id, lock=True)
    inventory = result[4] if result else None
    if inventory is None or payload.quantity > inventory.quantity - inventory.reserved_quantity:
        raise HTTPException(status_code=409, detail={"code": "insufficient_stock", "message": "Requested quantity is not available."})
    item.quantity = payload.quantity
    db.commit()
    return _cart_payload(db, _get_cart(db, principal.user.id))


@router.delete("/cart/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_cart_item(
    item_id: UUID,
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> None:
    item = db.scalar(
        select(CartItem)
        .join(Cart, Cart.id == CartItem.cart_id)
        .where(CartItem.id == item_id, Cart.customer_id == principal.user.id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "cart_item_not_found", "message": "Cart item was not found."})
    db.delete(item)
    db.commit()


@router.delete("/cart", status_code=status.HTTP_204_NO_CONTENT)
def clear_cart(
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> None:
    cart = _get_cart(db, principal.user.id)
    if cart:
        db.execute(delete(CartItem).where(CartItem.cart_id == cart.id))
        db.commit()


@router.post("/orders/delivery-quote")
@limiter.limit("20/minute")
def quote_checkout(
    request: Request,
    payload: CheckoutIn,
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> dict:
    """Preview the road-route distance and delivery fee for the current cart.

    The distances come from the routing service for the actual route between
    each retailer's pickup location and the chosen delivery point, so the
    quoted fee is the fee checkout will commit (COM-FEE-004).
    """

    return preview_checkout_quote(db, principal.user, payload)


@router.post("/orders", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def checkout(
    request: Request,
    payload: CheckoutIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=8, max_length=100),
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> dict:
    try:
        order = create_order(db, principal.user, payload, idempotency_key)
        db.commit()
        db.refresh(order)
        return order_payload(db, order)
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            existing = db.scalar(
                select(Order).where(Order.customer_id == principal.user.id, Order.idempotency_key == idempotency_key)
            )
            if existing:
                return order_payload(db, existing)
        raise HTTPException(status_code=409, detail={"code": "checkout_conflict", "message": "Cart changed during checkout. Review it and try again."}) from None


@router.get("/orders", response_model=list[OrderOut])
def my_orders(
    limit: int = 50,
    offset: int = 0,
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> list[dict]:
    orders = db.scalars(
        select(Order).where(Order.customer_id == principal.user.id).order_by(Order.created_at.desc()).limit(min(max(limit, 1), 100)).offset(max(offset, 0))
    ).all()
    return [order_payload(db, order) for order in orders]


@router.post("/orders/{order_id}/reorder")
@limiter.limit("10/minute")
def reorder(
    request: Request,
    order_id: UUID,
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> dict:
    order = db.get(Order, order_id)
    if order is None or order.customer_id != principal.user.id:
        raise HTTPException(status_code=404, detail={"code": "order_not_found", "message": "Order was not found."})
    cart = _get_cart(db, principal.user.id, create=True)
    order_items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    if not order_items:
        raise HTTPException(status_code=409, detail={"code": "nothing_to_reorder", "message": "This order has no available items to reorder."})
    additions = []
    for order_item in order_items:
        if order_item.retailer_product_id is None:
            raise HTTPException(status_code=409, detail={"code": "listing_unavailable", "message": f"{order_item.product_name} is no longer available."})
        result = _get_customer_listing(db, order_item.retailer_product_id, lock=True)
        if result is None:
            raise HTTPException(status_code=409, detail={"code": "listing_unavailable", "message": f"{order_item.product_name} is no longer available."})
        listing, product, retailer, retailer_user, inventory = result
        existing = db.scalar(
            select(CartItem).where(CartItem.cart_id == cart.id, CartItem.retailer_product_id == listing.id).with_for_update()
        )
        total_quantity = order_item.quantity + (existing.quantity if existing else 0)
        if (
            not listing.is_active
            or product.status != "ACTIVE"
            or retailer.status != "ACTIVE"
            or retailer.verification_status != "VERIFIED"
            or retailer_user.status != "ACTIVE"
            or inventory is None
            or total_quantity > inventory.quantity - inventory.reserved_quantity
        ):
            raise HTTPException(status_code=409, detail={"code": "listing_unavailable", "message": f"{order_item.product_name} is no longer available in that quantity."})
        additions.append((listing.id, order_item.quantity, existing))
    for listing_id, quantity, existing in additions:
        if existing:
            existing.quantity += quantity
        else:
            db.add(CartItem(cart_id=cart.id, retailer_product_id=listing_id, quantity=quantity))
    db.commit()
    return _cart_payload(db, _get_cart(db, principal.user.id))


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: UUID,
    principal: Principal = Depends(require_roles("CUSTOMER", "RETAILER", "DELIVERY_AGENT", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail={"code": "order_not_found", "message": "Order was not found."})
    if principal.user.role == "CUSTOMER" and order.customer_id != principal.user.id:
        raise HTTPException(status_code=404, detail={"code": "order_not_found", "message": "Order was not found."})
    if principal.user.role == "RETAILER":
        retailer = db.scalar(select(Retailer).where(Retailer.user_id == principal.user.id))
        owns_item = retailer and db.scalar(select(OrderItem.id).where(OrderItem.order_id == order.id, OrderItem.retailer_id == retailer.id))
        if not owns_item:
            raise HTTPException(status_code=404, detail={"code": "order_not_found", "message": "Order was not found."})
        result = order_payload(db, order)
        result["items"] = [item for item in result["items"] if item["retailer_id"] == retailer.id]
        result["deliveries"] = [delivery for delivery in result["deliveries"] if delivery["retailer_id"] == retailer.id]
        result["delivery_point_id"] = None
        result["pickup_point_id"] = None
        return result
    if principal.user.role == "DELIVERY_AGENT":
        assigned = db.scalar(
            select(DeliveryAssignment)
            .join(RetailerFulfillment, RetailerFulfillment.id == DeliveryAssignment.fulfillment_id)
            .where(RetailerFulfillment.order_id == order.id, DeliveryAssignment.agent_id == principal.user.id)
        )
        if not assigned:
            raise HTTPException(status_code=404, detail={"code": "order_not_found", "message": "Order was not found."})
        fulfillment = db.get(RetailerFulfillment, assigned.fulfillment_id)
        result = order_payload(db, order)
        result["items"] = [item for item in result["items"] if item["retailer_id"] == fulfillment.retailer_id]
        result["deliveries"] = [delivery for delivery in result["deliveries"] if delivery["id"] == assigned.id]
        result["delivery_point_id"] = None
        result["pickup_point_id"] = None
        return result
    return order_payload(db, order)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
@limiter.limit("10/minute")
def cancel_order(
    request: Request,
    order_id: UUID,
    principal: Principal = Depends(require_roles("CUSTOMER", "ADMIN")),
    db: Session = Depends(get_db),
) -> dict:
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None or (principal.user.role == "CUSTOMER" and order.customer_id != principal.user.id):
        raise HTTPException(status_code=404, detail={"code": "order_not_found", "message": "Order was not found."})
    if order.status not in {"PENDING", "CONFIRMED", "PREPARING", "READY", "PARTIALLY_REJECTED"}:
        raise HTTPException(status_code=409, detail={"code": "order_not_cancellable", "message": "This order can no longer be cancelled."})
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
        for assignment in assignments
    ):
        raise HTTPException(status_code=409, detail={"code": "delivery_in_progress", "message": "A delivery already in progress cannot be cancelled."})
    if any(
        assignment.status != "CANCELLED"
        and not is_delivery_assignment_transition_allowed(assignment.status, "CANCELLED")
        for assignment in assignments
    ):
        raise HTTPException(status_code=409, detail={"code": "delivery_state_conflict", "message": "A delivery assignment cannot be cancelled in its current state."})
    active_fulfillments = [
        fulfillment
        for fulfillment in fulfillments
        if is_fulfillment_transition_allowed(fulfillment.status, "CANCELLED")
    ]
    if any(
        fulfillment.status not in {"REJECTED", "CANCELLED"}
        and fulfillment not in active_fulfillments
        for fulfillment in fulfillments
    ):
        raise HTTPException(status_code=409, detail={"code": "fulfillment_state_conflict", "message": "A fulfillment cannot be cancelled in its current state."})
    for fulfillment in fulfillments:
        if fulfillment not in active_fulfillments:
            continue
        previous = fulfillment.status
        _release_fulfillment_inventory(db, fulfillment.id)
        fulfillment.status = "CANCELLED"
        db.add(RetailerFulfillmentEvent(fulfillment_id=fulfillment.id, actor_user_id=principal.user.id, previous_status=previous, new_status="CANCELLED"))
        retailer = db.get(Retailer, fulfillment.retailer_id)
        if retailer:
            db.add(NotificationOutbox(user_id=retailer.user_id, event_type="ORDER_CANCELLED", payload={"order_id": str(order.id)}))
    for assignment in assignments:
        if assignment.status == "CANCELLED":
            continue
        previous = assignment.status
        assignment.status = "CANCELLED"
        db.add(
            DeliveryEvent(
                assignment_id=assignment.id,
                actor_user_id=principal.user.id,
                previous_status=previous,
                new_status="CANCELLED",
                note="Order cancelled before physical pickup",
            )
        )
    # A captured online payment cannot be silently lost when an order is
    # cancelled. Reserve a full refund for each successful payment. The actual
    # provider-side refund remains a separate, auditable operation; until it is
    # confirmed the order payment_status stays PAID.
    successful_payments = db.scalars(
        select(Payment)
        .where(Payment.order_id == order.id, Payment.status == "SUCCESSFUL")
        .with_for_update()
    ).all()
    for payment in successful_payments:
        refund = reserve_refund_attempt(
            db,
            payment.id,
            amount_ugx=payment.amount_ugx,
            idempotency_key=f"order-cancellation:{order.id}:payment:{payment.id}",
            external_reference=f"order-cancellation:{order.id}:payment:{payment.id}",
        )
        if refund.status == "SUBMITTED":
            db.add(
                NotificationOutbox(
                    user_id=payment.customer_id,
                    event_type="REFUND_PENDING",
                    payload={
                        "order_id": str(order.id),
                        "order_number": order.order_number,
                        "payment_id": str(payment.id),
                        "refund_id": str(refund.id),
                        "amount_ugx": refund.amount_ugx,
                    },
                )
            )

    order.status = "CANCELLED"
    order.cancelled_at = utcnow()
    db.commit()
    db.refresh(order)
    return order_payload(db, order)


def _release_fulfillment_inventory(db: Session, fulfillment_id: UUID) -> None:
    fulfillment = db.get(RetailerFulfillment, fulfillment_id)
    if fulfillment is None or fulfillment.status in {"REJECTED", "CANCELLED", "DELIVERED"}:
        return
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == fulfillment.order_id, OrderItem.retailer_id == fulfillment.retailer_id)).all()
    for item in items:
        if item.retailer_product_id is None:
            continue
        inventory = db.scalar(select(Inventory).where(Inventory.retailer_product_id == item.retailer_product_id).with_for_update())
        if inventory:
            inventory.reserved_quantity = max(0, inventory.reserved_quantity - item.quantity)


@router.get("/retailers/me/fulfillments")
def retailer_fulfillments(
    principal: Principal = Depends(require_roles("RETAILER")),
    db: Session = Depends(get_db),
) -> list[dict]:
    retailer = db.scalar(select(Retailer).where(Retailer.user_id == principal.user.id))
    if retailer is None:
        raise HTTPException(status_code=404, detail="Retailer profile was not found.")
    rows = db.execute(
        select(RetailerFulfillment, Order)
        .join(Order, Order.id == RetailerFulfillment.order_id)
        .where(RetailerFulfillment.retailer_id == retailer.id)
        .order_by(RetailerFulfillment.created_at.desc())
        .limit(100)
    ).all()
    return [
        {
            "id": fulfillment.id,
            "order_id": order.id,
            "order_number": order.order_number,
            "status": fulfillment.status,
            "created_at": fulfillment.created_at,
            "items": [
                {"name": item.product_name, "quantity": item.quantity, "unit_price_ugx": item.unit_price_ugx}
                for item in db.scalars(select(OrderItem).where(OrderItem.order_id == order.id, OrderItem.retailer_id == retailer.id)).all()
            ],
        }
        for fulfillment, order in rows
    ]


@router.post("/retailers/me/fulfillments/{fulfillment_id}/{action}")
def update_fulfillment(
    fulfillment_id: UUID,
    action: str,
    payload: FulfillmentAction | None = None,
    principal: Principal = Depends(require_roles("RETAILER")),
    db: Session = Depends(get_db),
) -> dict:
    allowed = {"confirm", "reject", "preparing", "ready"}
    if action not in allowed:
        raise HTTPException(status_code=404, detail={"code": "action_not_found", "message": "Fulfillment action was not found."})
    retailer = db.scalar(select(Retailer).where(Retailer.user_id == principal.user.id))
    fulfillment_reference = db.scalar(
        select(RetailerFulfillment)
        .where(RetailerFulfillment.id == fulfillment_id, RetailerFulfillment.retailer_id == retailer.id if retailer else False)
    )
    if fulfillment_reference is None:
        raise HTTPException(status_code=404, detail={"code": "fulfillment_not_found", "message": "Fulfillment was not found."})
    order = db.scalar(select(Order).where(Order.id == fulfillment_reference.order_id).with_for_update())
    fulfillment = db.scalar(
        select(RetailerFulfillment)
        .where(
            RetailerFulfillment.id == fulfillment_id,
            RetailerFulfillment.retailer_id == retailer.id if retailer else False,
        )
        .with_for_update()
    )
    if fulfillment is None or order is None:
        raise HTTPException(status_code=404, detail={"code": "fulfillment_not_found", "message": "Fulfillment was not found."})
    target_status = {
        "confirm": "CONFIRMED",
        "reject": "REJECTED",
        "preparing": "PREPARING",
        "ready": "READY",
    }[action]
    if not is_fulfillment_transition_allowed(fulfillment.status, target_status):
        raise HTTPException(status_code=409, detail={"code": "invalid_transition", "message": f"Cannot {action} a {fulfillment.status.lower()} fulfillment."})
    previous_status = fulfillment.status
    now = utcnow()
    if action == "confirm":
        fulfillment.status = "CONFIRMED"
        fulfillment.confirmed_at = now
        order.confirmed_at = order.confirmed_at or now
    elif action == "reject":
        assignment = db.scalar(
            select(DeliveryAssignment)
            .where(DeliveryAssignment.fulfillment_id == fulfillment.id)
            .with_for_update()
        )
        _adjust_order_after_rejection(db, order, fulfillment)
        _release_fulfillment_inventory(db, fulfillment.id)
        fulfillment.status = "REJECTED"
        fulfillment.rejected_at = now
        fulfillment.rejection_reason = payload.reason if payload else None
        if assignment and assignment.status == "UNASSIGNED":
            assignment.status = "CANCELLED"
            db.add(
                DeliveryEvent(
                    assignment_id=assignment.id,
                    actor_user_id=principal.user.id,
                    previous_status="UNASSIGNED",
                    new_status="CANCELLED",
                    note="Retailer rejected fulfillment",
                )
            )
    elif action == "preparing":
        fulfillment.status = "PREPARING"
    elif action == "ready":
        fulfillment.status = "READY"
        fulfillment.ready_at = now
        dispatch_ready_fulfillment(db, fulfillment.id)
    db.add(
        RetailerFulfillmentEvent(
            fulfillment_id=fulfillment.id,
            actor_user_id=principal.user.id,
            previous_status=previous_status,
            new_status=fulfillment.status,
            note=payload.reason if action == "reject" and payload else None,
        )
    )
    recompute_order_status(db, order)
    db.add(NotificationOutbox(user_id=order.customer_id, event_type=f"ORDER_{fulfillment.status}", payload={"order_id": str(order.id), "order_number": order.order_number}))
    db.commit()
    return {"id": fulfillment.id, "order_id": order.id, "status": fulfillment.status, "order_status": order.status}


def _adjust_order_after_rejection(db: Session, order: Order, fulfillment: RetailerFulfillment) -> None:
    payments = db.scalars(select(Payment).where(Payment.order_id == order.id).with_for_update()).all()
    if order.payment_status == "PAID" or any(payment.status == "PENDING" for payment in payments):
        raise HTTPException(status_code=409, detail={"code": "refund_or_payment_resolution_required", "message": "Resolve the payment or refund before rejecting this retailer fulfilment."})
    items = db.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id, OrderItem.retailer_id == fulfillment.retailer_id)
    ).all()
    rejected_subtotal = sum(item.line_total_ugx for item in items)
    order.subtotal_ugx = max(0, order.subtotal_ugx - rejected_subtotal)
    committed_fee = remove_committed_delivery_quote(db, fulfillment.id)
    if committed_fee is not None:
        # The fulfillment owns its own committed, routing-priced delivery fee.
        fee_share = committed_fee
    else:
        # Orders created before per-fulfillment quote snapshots have no committed
        # fee; they keep the existing equal-share behaviour.
        fulfillment_count = db.scalar(
            select(func.count(RetailerFulfillment.id)).where(
                RetailerFulfillment.order_id == order.id,
                RetailerFulfillment.status.not_in(["REJECTED", "CANCELLED"]),
            )
        ) or 1
        fee_share = order.delivery_fee_ugx // fulfillment_count if order.delivery_method == "DELIVERY" else 0
    order.delivery_fee_ugx = max(0, order.delivery_fee_ugx - fee_share)
    order.total_ugx = order.subtotal_ugx + order.delivery_fee_ugx
    # WEWE is online-payment-only. Rejection adjusts the order amount, but it
    # Any existing online payment attempt must be resolved/refunded before the
    # fulfillment can be rejected (enforced above).


@router.post("/orders/{order_id}/pickup-confirm", response_model=OrderOut)
def confirm_customer_pickup(
    order_id: UUID,
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> dict:
    order = db.scalar(select(Order).where(Order.id == order_id, Order.customer_id == principal.user.id).with_for_update())
    if order is None:
        raise HTTPException(status_code=404, detail={"code": "order_not_found", "message": "Order was not found."})
    if order.delivery_method != "PICKUP" or order.status not in {"READY", "PARTIALLY_REJECTED"}:
        raise HTTPException(status_code=409, detail={"code": "pickup_not_ready", "message": "This order is not ready for customer pickup."})
    fulfillments = db.scalars(select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id).with_for_update()).all()
    for fulfillment in fulfillments:
        if fulfillment.status == "READY":
            fulfillment.status = "DELIVERED"
            _consume_fulfillment_inventory(db, fulfillment)
        elif fulfillment.status != "REJECTED":
            raise HTTPException(status_code=409, detail={"code": "pickup_not_ready", "message": "Every accepted item must be ready before pickup."})
    recompute_order_status(db, order)
    # Payment is settled online: confirming a pickup never marks a payment
    # successful. Mobile-money outcomes arrive through the provider webhook.
    db.commit()
    db.refresh(order)
    return order_payload(db, order)


def _consume_fulfillment_inventory(db: Session, fulfillment: RetailerFulfillment) -> None:
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == fulfillment.order_id, OrderItem.retailer_id == fulfillment.retailer_id)).all()
    for item in items:
        if item.retailer_product_id is None:
            continue
        inventory = db.scalar(select(Inventory).where(Inventory.retailer_product_id == item.retailer_product_id).with_for_update())
        if inventory:
            inventory.reserved_quantity = max(0, inventory.reserved_quantity - item.quantity)
            inventory.quantity = max(0, inventory.quantity - item.quantity)


@router.post("/orders/{order_id}/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def create_payment(
    request: Request,
    order_id: UUID,
    payload: PaymentCreate,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        min_length=8,
        max_length=180,
    ),
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> dict:
    order = db.scalar(select(Order).where(Order.id == order_id, Order.customer_id == principal.user.id).with_for_update())
    if order is None:
        raise HTTPException(status_code=404, detail={"code": "order_not_found", "message": "Order was not found."})
    prior_attempt = db.scalar(
        select(Payment).where(Payment.idempotency_key == idempotency_key).with_for_update()
    ) if idempotency_key else None
    if prior_attempt:
        if (
            prior_attempt.customer_id != principal.user.id
            or prior_attempt.order_id != order.id
            or prior_attempt.amount_ugx != order.total_ugx
            or prior_attempt.currency != order.currency
            or prior_attempt.method != payload.method
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "idempotency_key_conflict", "message": "This key was already used for a different payment request."},
            )
        return _payment_response(prior_attempt, idempotent_replay=True)
    if order.status in {"CANCELLED", "REJECTED", "FAILED", "DELIVERED", "PARTIALLY_DELIVERED"}:
        raise HTTPException(status_code=409, detail={"code": "payment_not_allowed", "message": "Payment cannot be started for this order."})
    if order.payment_status == "PAID":
        raise HTTPException(status_code=409, detail={"code": "already_paid", "message": "This order is already paid."})
    blocking_attempt = db.scalar(
        select(Payment.id).where(
            Payment.order_id == order.id,
            Payment.status.in_(["PENDING", "UNKNOWN", "SUCCESSFUL"]),
        )
    )
    if blocking_attempt:
        raise HTTPException(status_code=409, detail={"code": "payment_pending", "message": "A payment attempt is already pending for this order."})
    if not (payload.email or principal.user.email):
        raise HTTPException(status_code=422, detail={"code": "payment_email_required", "message": "Add an email address for the payment receipt before paying."})
    # Online payment only: WEWE is online-payment-only and cash is out of scope
    # (COM-PAY-004 / COM-MULTI-001), so a configured provider adapter is
    # required before any charge is created.
    try:
        provider = payment_providers.get(payload.method)
    except PaymentProviderUnavailable:
        raise HTTPException(status_code=503, detail={"code": "payment_provider_unavailable", "message": "This payment method is not configured yet."}) from None
    now = utcnow()
    internal_reference = f"{order.order_number}-{secrets.token_hex(8).upper()}"
    payment = Payment(
        order_id=order.id,
        customer_id=principal.user.id,
        amount_ugx=order.total_ugx,
        currency="UGX",
        method=payload.method,
        provider=provider.name,
        attempt_reference=internal_reference,
        idempotency_key=idempotency_key,
        status="PENDING",
        initiated_at=now,
    )
    order.payment_status = "PENDING"
    db.add(payment)
    db.commit()
    db.refresh(payment)
    checkout_url = None
    if provider:  # an online method always has a provider adapter here
        try:
            initiation = provider.initiate(
                PaymentRequest(
                    reference=payment.attempt_reference,
                    amount_ugx=payment.amount_ugx,
                    currency="UGX",
                    phone=payload.phone or "",
                    callback_url=f"{get_settings().payment_callback_url}/{provider.name}",
                    method=payload.method,
                    customer_email=payload.email or principal.user.email,
                    customer_name=principal.user.name,
                )
            )
            payment.provider_reference = initiation.provider_reference
            checkout_url = initiation.checkout_url
            db.commit()
            db.refresh(payment)
        except FlutterwaveAPIError as exc:
            logger.warning(
                "Flutterwave payment initiation rejected payment_id=%s diagnostics=%s",
                payment.id,
                exc.diagnostic(),
            )
            payment_id = payment.id
            db.rollback()
            locked_order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
            locked_payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
            if locked_order is None or locked_payment is None:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "code": "payment_provider_error",
                        "message": "Flutterwave rejected the payment request and the payment record could not be updated.",
                        "payment_id": str(payment_id),
                        "provider": exc.diagnostic(),
                    },
                ) from None
            if locked_payment.status == "PENDING":
                locked_payment.status = "FAILED"
                db.flush()
                locked_order.payment_status = aggregate_payment_status(
                    db.scalars(select(Payment.status).where(Payment.order_id == locked_order.id)).all()
                )
                record_reconciliation_unresolved(
                    db,
                    locked_payment.id,
                    evidence={
                        "reason": "provider_validation_error",
                        "provider": "FLUTTERWAVE",
                        "stage": exc.stage,
                        "provider_code": exc.provider_code,
                        "request_id": exc.request_id,
                    },
                )
                db.commit()
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "payment_provider_error",
                    "message": "Flutterwave rejected the payment request.",
                    "payment_id": str(payment_id),
                    "provider": exc.diagnostic(),
                },
            ) from None
        except Exception as exc:
            logger.exception("Payment initiation outcome uncertain payment_id=%s", payment.id)
            payment_id = payment.id
            db.rollback()
            locked_order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
            locked_payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
            if locked_order is None or locked_payment is None:
                raise HTTPException(
                    status_code=502,
                    detail={"code": "payment_initiation_uncertain", "message": "The payment result could not be confirmed. Do not retry this payment yet."},
                ) from exc
            if locked_payment.status == "PENDING":
                locked_payment.status = "UNKNOWN"
                db.flush()
                locked_order.payment_status = aggregate_payment_status(
                    db.scalars(select(Payment.status).where(Payment.order_id == locked_order.id)).all()
                )
                record_reconciliation_unresolved(
                    db,
                    locked_payment.id,
                    evidence={"reason": "provider_initiation_exception", "error_type": type(exc).__name__},
                )
                db.commit()
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "payment_initiation_uncertain",
                    "message": "The payment result could not be confirmed. Do not retry this payment yet.",
                    "payment_id": str(payment_id),
                },
            ) from None
    return _payment_response(payment, checkout_url=checkout_url)


def _payment_response(
    payment: Payment,
    checkout_url: str | None = None,
    idempotent_replay: bool = False,
) -> dict:
    return {
        "id": payment.id,
        "order_id": payment.order_id,
        "amount_ugx": payment.amount_ugx,
        "currency": payment.currency,
        "method": payment.method,
        "provider": payment.provider,
        "provider_reference": payment.provider_reference,
        "status": payment.status,
        "attempt_reference": payment.attempt_reference,
        "created_at": payment.created_at,
        "initiated_at": payment.initiated_at,
        "resolved_at": payment.resolved_at,
        "checkout_url": checkout_url,
        "idempotent_replay": idempotent_replay,
    }
