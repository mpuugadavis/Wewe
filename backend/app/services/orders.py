import secrets
from collections import defaultdict
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Cart,
    CartItem,
    DeliveryAssignment,
    DeliveryPoint,
    Inventory,
    NotificationOutbox,
    Order,
    OrderItem,
    Payment,
    PaymentRefund,
    PickupPoint,
    Product,
    Retailer,
    RetailerFulfillment,
    RetailerProduct,
    User,
    utcnow,
)
from app.schemas import CheckoutIn
from app.services.delivery_pricing import (
    DELIVERY,
    PICKUP,
    DeliveryPriceQuote,
    DeliveryPricingError,
    build_delivery_quote,
    commit_delivery_quote,
    committed_quotes_for_order,
    resolve_delivery_pricing_config,
    calculate_multi_retailer_delivery_total,
)
from app.services.delivery_routing import DeliveryRoutingError, resolve_route_distances
from app.services.platform_economics import snapshot_order_commission


def _checkout_delivery_quotes(
    db: Session, checkout: CheckoutIn, retailer_ids: list[UUID], delivery_point: DeliveryPoint | None
) -> tuple[dict[UUID, DeliveryPriceQuote], str | None]:
    """Price every retailer fulfillment independently (COM-FEE-001/002/003).

    For a delivery order the road-route distance comes from the routing
    service: one real route per retailer leg between that retailer's pickup
    location and the customer's delivery point (COM-FEE-004). Distances are
    never taken from the caller, and a route that cannot be produced refuses
    the checkout instead of being guessed (COM-FEE-009).

    Returns the per-retailer quotes plus the routing provider name (``None``
    for pickup, which has no route and is always UGX 0).
    """

    config = _resolve_pricing_config_or_unavailable(db)
    if checkout.delivery_method == PICKUP:
        quotes = {
            retailer_id: build_delivery_quote(config, retailer_id=retailer_id, mode=PICKUP)
            for retailer_id in retailer_ids
        }
        return quotes, None

    if delivery_point is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "delivery_point_not_found", "message": "Delivery point was not found."},
        )
    try:
        routes, provider_name = resolve_route_distances(
            db, destination=delivery_point, retailer_ids=retailer_ids
        )
    except DeliveryRoutingError as exc:
        raise exc.as_http_exception() from exc

    quotes = {}
    for retailer_id in retailer_ids:
        route = routes[retailer_id]
        try:
            quotes[retailer_id] = build_delivery_quote(
                config,
                retailer_id=retailer_id,
                mode=DELIVERY,
                route_distance_km=route.distance_km,
                distance_source=route.source,
            )
        except DeliveryPricingError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
    return quotes, provider_name


def _resolve_pricing_config_or_unavailable(db: Session):
    try:
        return resolve_delivery_pricing_config(db)
    except DeliveryPricingError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "invalid_platform_setting", "message": "Delivery pricing is temporarily unavailable."},
        ) from exc


def _resolve_checkout_destination(
    db: Session, customer: User, checkout: CheckoutIn
) -> tuple[DeliveryPoint | None, PickupPoint | None]:
    """Validate and return the checkout destination (delivery or pickup point)."""

    if checkout.delivery_method == "DELIVERY":
        delivery_point = db.get(DeliveryPoint, checkout.delivery_point_id)
        if (
            delivery_point is None
            or not delivery_point.is_active
            or (delivery_point.is_private and delivery_point.owner_user_id != customer.id)
        ):
            raise HTTPException(
                status_code=404,
                detail={"code": "delivery_point_not_found", "message": "Delivery point was not found."},
            )
        return delivery_point, None

    pickup_point = db.get(PickupPoint, checkout.pickup_point_id)
    if pickup_point is None or pickup_point.operating_status != "OPEN":
        raise HTTPException(
            status_code=404,
            detail={"code": "pickup_point_unavailable", "message": "Pickup point is not available."},
        )
    pickup_location = db.get(DeliveryPoint, pickup_point.delivery_point_id)
    if pickup_location is None or not pickup_location.is_active:
        raise HTTPException(
            status_code=404,
            detail={"code": "pickup_point_unavailable", "message": "Pickup point is not available."},
        )
    return None, pickup_point


def create_order(db: Session, customer: User, checkout: CheckoutIn, idempotency_key: str | None) -> Order:
    if idempotency_key:
        prior = db.scalar(
            select(Order).where(Order.customer_id == customer.id, Order.idempotency_key == idempotency_key)
        )
        if prior:
            return prior
    cart = db.scalar(select(Cart).where(Cart.customer_id == customer.id).with_for_update())
    if cart is None:
        raise HTTPException(status_code=409, detail={"code": "empty_cart", "message": "Add an item before checking out."})
    lines = list(
        db.execute(
            select(CartItem, RetailerProduct, Product, Retailer, User)
            .join(RetailerProduct, RetailerProduct.id == CartItem.retailer_product_id)
            .join(Product, Product.id == RetailerProduct.product_id)
            .join(Retailer, Retailer.id == RetailerProduct.retailer_id)
            .join(User, User.id == Retailer.user_id)
            .where(CartItem.cart_id == cart.id)
            .order_by(RetailerProduct.id)
            .with_for_update()
        ).all()
    )
    if not lines:
        raise HTTPException(status_code=409, detail={"code": "empty_cart", "message": "Add an item before checking out."})
    inventory_by_listing: dict[UUID, Inventory] = {}
    for cart_item, listing, product, retailer, retailer_user in lines:
        if (
            not listing.is_active
            or product.status != "ACTIVE"
            or retailer.status != "ACTIVE"
            or retailer.verification_status != "VERIFIED"
            or retailer_user.status != "ACTIVE"
        ):
            raise HTTPException(status_code=409, detail={"code": "listing_unavailable", "message": f"{product.name} is no longer available."})
        inventory = db.scalar(
            select(Inventory).where(Inventory.retailer_product_id == listing.id).with_for_update()
        )
        if inventory is None:
            raise HTTPException(status_code=409, detail={"code": "inventory_missing", "message": "An item is missing its inventory record."})
        available = inventory.quantity - inventory.reserved_quantity
        if cart_item.quantity > available:
            raise HTTPException(status_code=409, detail={"code": "insufficient_stock", "message": f"Only {available} of {product.name} are available."})
        inventory_by_listing[listing.id] = inventory
    delivery_point, pickup_point = _resolve_checkout_destination(db, customer, checkout)
    grouped: dict[UUID, list[tuple]] = defaultdict(list)
    subtotal = 0
    for line in lines:
        cart_item, listing, product, retailer, retailer_user = line
        line_total = listing.price_ugx * cart_item.quantity
        subtotal += line_total
        grouped[retailer.id].append((cart_item, listing, product, retailer))
    quotes, _routing_provider = _checkout_delivery_quotes(db, checkout, list(grouped), delivery_point)
    pricing_config = _resolve_pricing_config_or_unavailable(db)
    delivery_total = calculate_multi_retailer_delivery_total(quotes.values(), pricing_config)
    order = Order(
        order_number=f"WW-{secrets.token_hex(5).upper()}",
        customer_id=customer.id,
        delivery_point_id=delivery_point.id if delivery_point else None,
        pickup_point_id=pickup_point.delivery_point_id if pickup_point else None,
        delivery_method=checkout.delivery_method,
        currency="UGX",
        subtotal_ugx=subtotal,
        gross_delivery_fee_ugx=delivery_total.gross_delivery_fee_ugx,
        multi_retailer_discount_ugx=delivery_total.multi_retailer_discount_ugx,
        multi_retailer_discount_percent=delivery_total.discount_percent,
        delivery_fee_ugx=delivery_total.delivery_fee_ugx,
        total_ugx=subtotal + delivery_total.delivery_fee_ugx,
        status="PENDING",
        idempotency_key=idempotency_key,
    )
    snapshot_order_commission(db, order)
    db.add(order)
    db.flush()
    fulfillment_ids: list[tuple[RetailerFulfillment, Retailer]] = []
    for retailer_id, retailer_lines in grouped.items():
        retailer = retailer_lines[0][3]
        fulfillment = RetailerFulfillment(order_id=order.id, retailer_id=retailer_id, status="PENDING")
        db.add(fulfillment)
        db.flush()
        quote = quotes[retailer_id]
        commit_delivery_quote(db, quote, fulfillment_id=fulfillment.id)
        fulfillment_ids.append((fulfillment, retailer))
        db.add(
            NotificationOutbox(
                user_id=retailer.user_id,
                event_type="ORDER_PLACED",
                payload={"order_id": str(order.id), "order_number": order.order_number},
            )
        )
        for cart_item, listing, product, _retailer in retailer_lines:
            inventory_by_listing[listing.id].reserved_quantity += cart_item.quantity
            db.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    retailer_product_id=listing.id,
                    retailer_id=retailer_id,
                    product_name=product.name,
                    sku_snapshot=listing.sku,
                    unit_price_ugx=listing.price_ugx,
                    quantity=cart_item.quantity,
                    line_total_ugx=listing.price_ugx * cart_item.quantity,
                )
            )
        if checkout.delivery_method == "DELIVERY":
            db.add(
                DeliveryAssignment(
                    fulfillment_id=fulfillment.id,
                    status="UNASSIGNED",
                    pickup_point_id=retailer.location_id,
                    dropoff_point_id=delivery_point.id,
                )
            )
    customer_notification: dict[str, Any] = {
        "order_id": str(order.id),
        "order_number": order.order_number,
    }
    db.add(
        NotificationOutbox(
            user_id=customer.id,
            event_type="ORDER_PLACED",
            payload=customer_notification,
        )
    )
    db.execute(delete(CartItem).where(CartItem.cart_id == cart.id))
    db.flush()
    return order


def preview_checkout_quote(db: Session, customer: User, checkout: CheckoutIn) -> dict[str, Any]:
    """Price the current cart without creating an order.

    Uses the same routing-service lookup and COM-FEE rules as checkout, so the
    road-route distance and delivery fee shown to the customer are exactly the
    ones the order will charge.
    """

    cart = db.scalar(select(Cart).where(Cart.customer_id == customer.id))
    if cart is None:
        raise HTTPException(
            status_code=409, detail={"code": "empty_cart", "message": "Add an item before checking out."}
        )
    rows = db.execute(
        select(CartItem, RetailerProduct, Product, Retailer)
        .join(RetailerProduct, RetailerProduct.id == CartItem.retailer_product_id)
        .join(Product, Product.id == RetailerProduct.product_id)
        .join(Retailer, Retailer.id == RetailerProduct.retailer_id)
        .where(CartItem.cart_id == cart.id)
        .order_by(RetailerProduct.id)
    ).all()
    if not rows:
        raise HTTPException(
            status_code=409, detail={"code": "empty_cart", "message": "Add an item before checking out."}
        )

    retailer_ids: list[UUID] = []
    retailer_names: dict[UUID, str] = {}
    subtotal = 0
    for cart_item, listing, product, retailer in rows:
        subtotal += listing.price_ugx * cart_item.quantity
        if retailer.id not in retailer_names:
            retailer_names[retailer.id] = retailer.business_name
            retailer_ids.append(retailer.id)

    delivery_point, _pickup_point = _resolve_checkout_destination(db, customer, checkout)
    quotes, routing_provider = _checkout_delivery_quotes(db, checkout, retailer_ids, delivery_point)
    pricing_config = _resolve_pricing_config_or_unavailable(db)
    delivery_total = calculate_multi_retailer_delivery_total(quotes.values(), pricing_config)
    return {
        "currency": "UGX",
        "delivery_method": checkout.delivery_method,
        "routing_provider": routing_provider,
        "subtotal_ugx": subtotal,
        "gross_delivery_fee_ugx": delivery_total.gross_delivery_fee_ugx,
        "multi_retailer_discount_ugx": delivery_total.multi_retailer_discount_ugx,
        "multi_retailer_discount_percent": str(delivery_total.discount_percent),
        "delivery_fee_ugx": delivery_total.delivery_fee_ugx,
        "total_ugx": subtotal + delivery_total.delivery_fee_ugx,
        "fulfillments": [
            {
                "retailer_id": retailer_id,
                "retailer_name": retailer_names[retailer_id],
                "mode": quotes[retailer_id].mode,
                "route_distance_km": str(quotes[retailer_id].route_distance_km)
                if quotes[retailer_id].route_distance_km is not None
                else None,
                "distance_source": quotes[retailer_id].distance_source,
                "delivery_fee_ugx": quotes[retailer_id].delivery_fee_ugx,
            }
            for retailer_id in retailer_ids
        ],
    }


def order_payload(db: Session, order: Order) -> dict:
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)).all()
    deliveries = db.execute(
        select(DeliveryAssignment, RetailerFulfillment)
        .join(RetailerFulfillment, RetailerFulfillment.id == DeliveryAssignment.fulfillment_id)
        .where(RetailerFulfillment.order_id == order.id)
        .order_by(DeliveryAssignment.created_at)
    ).all()
    return {
        "id": order.id,
        "order_number": order.order_number,
        "customer_id": order.customer_id,
        "delivery_point_id": order.delivery_point_id,
        "pickup_point_id": order.pickup_point_id,
        "delivery_method": order.delivery_method,
        "currency": order.currency,
        "subtotal_ugx": order.subtotal_ugx,
        "gross_delivery_fee_ugx": order.gross_delivery_fee_ugx,
        "multi_retailer_discount_ugx": order.multi_retailer_discount_ugx,
        "multi_retailer_discount_percent": str(order.multi_retailer_discount_percent),
        "delivery_fee_ugx": order.delivery_fee_ugx,
        "total_ugx": order.total_ugx,
        "platform_commission_percent": str(order.platform_commission_percent),
        "platform_commission_ugx": order.platform_commission_ugx,
        "status": order.status,
        "payment_status": order.payment_status,
        "created_at": order.created_at,
        "refunds": [
            {
                "id": refund.id,
                "payment_id": refund.payment_id,
                "amount_ugx": refund.amount_ugx,
                "status": refund.status,
                "external_reference": refund.external_reference,
                "created_at": refund.created_at,
                "resolved_at": refund.resolved_at,
            }
            for refund in db.scalars(
                select(PaymentRefund)
                .join(Payment, Payment.id == PaymentRefund.payment_id)
                .where(Payment.order_id == order.id)
                .order_by(PaymentRefund.created_at.desc())
            ).all()
        ],
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product_name,
                "retailer_id": item.retailer_id,
                "unit_price_ugx": item.unit_price_ugx,
                "quantity": item.quantity,
                "line_total_ugx": item.line_total_ugx,
            }
            for item in items
        ],
        "deliveries": [
            {"id": assignment.id, "retailer_id": fulfillment.retailer_id, "status": assignment.status,
             "assigned_at": assignment.assigned_at, "accepted_at": assignment.accepted_at,
             "picked_up_at": assignment.picked_up_at, "delivered_at": assignment.delivered_at}
            for assignment, fulfillment in deliveries
        ],
        "delivery_quotes": [
            {
                "fulfillment_id": quote.fulfillment_id,
                "retailer_id": quote.retailer_id,
                "mode": quote.mode,
                "route_distance_km": str(quote.route_distance_km) if quote.route_distance_km is not None else None,
                "distance_source": quote.distance_source,
                "base_fee_ugx": quote.base_fee_ugx,
                "price_per_km_ugx": str(quote.price_per_km_ugx),
                "minimum_fee_ugx": quote.minimum_fee_ugx,
                "rounding_increment_ugx": quote.rounding_increment_ugx,
                "rounding_tie_break": quote.rounding_tie_break,
                "pricing_version": quote.pricing_version,
                "currency": quote.currency,
                "delivery_fee_ugx": quote.delivery_fee_ugx,
                "quoted_at": quote.quoted_at,
                "removed_at": quote.removed_at,
            }
            for quote in committed_quotes_for_order(db, order.id)
        ],
    }


def recompute_order_status(db: Session, order: Order) -> None:
    fulfillments = list(db.scalars(select(RetailerFulfillment).where(RetailerFulfillment.order_id == order.id)).all())
    if not fulfillments:
        return
    states = {fulfillment.status for fulfillment in fulfillments}
    terminal = states.issubset({"DELIVERED", "REJECTED", "CANCELLED"})
    if terminal and "DELIVERED" in states and states != {"DELIVERED"}:
        order.status = "PARTIALLY_DELIVERED"
        order.delivered_at = utcnow()
    elif terminal and states == {"DELIVERED"}:
        order.status = "DELIVERED"
        order.delivered_at = utcnow()
    elif terminal and states == {"REJECTED"}:
        order.status = "REJECTED"
    elif terminal and states == {"CANCELLED"}:
        order.status = "CANCELLED"
        order.cancelled_at = order.cancelled_at or utcnow()
    elif "OUT_FOR_DELIVERY" in states:
        order.status = "OUT_FOR_DELIVERY"
    elif "REJECTED" in states:
        order.status = "PARTIALLY_REJECTED"
    elif "CANCELLED" in states:
        # Mixed cancellation outcomes have no approved aggregate status; preserve the existing projection.
        return
    elif states == {"READY"}:
        order.status = "READY"
    elif "PREPARING" in states or "READY" in states:
        order.status = "PREPARING"
    elif states == {"CONFIRMED"}:
        order.status = "CONFIRMED"
    else:
        order.status = "PENDING"
