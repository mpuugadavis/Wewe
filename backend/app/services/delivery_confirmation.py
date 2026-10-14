"""Issue customer-only handover codes in the assignment transaction."""
import secrets

from sqlalchemy.orm import Session

from app.models import DeliveryAssignment, NotificationOutbox, Order, User, RetailerFulfillment, Retailer
from app.security import hash_token


def issue_delivery_confirmation(db: Session, assignment: DeliveryAssignment, order: Order) -> None:
    code = f"{secrets.randbelow(100_000_000):08d}"
    assignment.confirmation_code_hash = hash_token(code)
    fulfillment = db.get(RetailerFulfillment, assignment.fulfillment_id)
    retailer = db.get(Retailer, fulfillment.retailer_id) if fulfillment else None
    shop = retailer.business_name if retailer else "your retailer"
    message = (
        f"A rider has been assigned to your delivery from {shop} for order {order.order_number}. "
        f"Your delivery handover code is {code}. "
        "Share it with your rider only when they arrive and you have received this delivery. "
        "Each delivery has its own code; a new assignment replaces the previous code."
    )
    payload = {
        "order_id": str(order.id), "order_number": order.order_number,
        "assignment_id": str(assignment.id), "fulfillment_id": str(assignment.fulfillment_id),
        "confirmation_code": code, "message": message,
    }
    db.add(NotificationOutbox(user_id=order.customer_id, event_type="DELIVERY_ASSIGNED", payload=payload))
    customer = db.get(User, order.customer_id)
    if customer and customer.email:
        db.add(NotificationOutbox(
            user_id=order.customer_id, channel="EMAIL", event_type="DELIVERY_ASSIGNED",
            payload={**payload, "to": customer.email,
                     "subject": f"WEWE delivery code for {order.order_number}", "body": message},
        ))
