"""Transactional dashboard and email notices for verification status changes."""
from app.models import NotificationOutbox, User


def notify_verification(db, user_id, role, previous, status):
    if previous == status:
        return
    user = db.get(User, user_id)
    label = "retailer" if role == "RETAILER" else "rider"
    message = (f"Your WEWE {label} account has been verified. " +
               ("You can now manage products and fulfil orders." if role == "RETAILER" else
                "Go online and share your location to receive nearby delivery offers.")) if status == "VERIFIED" else f"Your WEWE {label} verification status is now {status.lower()}. Check your profile or contact support."
    payload = {"message": message, "verification_status": status}
    event = f"{role}_{status}"
    db.add(NotificationOutbox(user_id=user_id, event_type=event, payload=payload))
    if user and user.email:
        db.add(NotificationOutbox(user_id=user_id, channel="EMAIL", event_type=event,
            payload={**payload, "to": user.email, "subject": "WEWE account verification update", "body": message}))
