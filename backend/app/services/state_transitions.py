from collections.abc import Iterable


PAYMENT_TRANSITIONS = {
    "PENDING": frozenset({"UNKNOWN", "SUCCESSFUL", "FAILED"}),
    "UNKNOWN": frozenset({"SUCCESSFUL", "FAILED"}),
    "SUCCESSFUL": frozenset({"REFUNDED"}),
    "FAILED": frozenset(),
    "REFUNDED": frozenset(),
}

FULFILLMENT_TRANSITIONS = {
    "PENDING": frozenset({"CONFIRMED", "REJECTED", "CANCELLED"}),
    "CONFIRMED": frozenset({"PREPARING", "READY", "CANCELLED"}),
    "PREPARING": frozenset({"READY", "CANCELLED"}),
    "READY": frozenset({"OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"}),
    "OUT_FOR_DELIVERY": frozenset({"DELIVERED"}),
    "REJECTED": frozenset(),
    "CANCELLED": frozenset(),
    "DELIVERED": frozenset(),
}

DELIVERY_ASSIGNMENT_TRANSITIONS = {
    "UNASSIGNED": frozenset({"ACCEPTED", "CANCELLED"}),
    "ACCEPTED": frozenset({"PICKED_UP", "CANCELLED"}),
    "PICKED_UP": frozenset({"OUT_FOR_DELIVERY"}),
    "OUT_FOR_DELIVERY": frozenset({"DELIVERED"}),
    "DELIVERED": frozenset(),
    "CANCELLED": frozenset(),
}


def is_payment_transition_allowed(current: str, target: str) -> bool:
    return target in PAYMENT_TRANSITIONS.get(current, frozenset())


def is_fulfillment_transition_allowed(current: str, target: str) -> bool:
    return target in FULFILLMENT_TRANSITIONS.get(current, frozenset())


def is_delivery_assignment_transition_allowed(current: str, target: str) -> bool:
    return target in DELIVERY_ASSIGNMENT_TRANSITIONS.get(current, frozenset())


def aggregate_payment_status(statuses: Iterable[str]) -> str:
    payment_statuses = set(statuses)
    if "SUCCESSFUL" in payment_statuses:
        return "PAID"
    if payment_statuses.intersection({"PENDING", "UNKNOWN"}):
        return "PENDING"
    if "REFUNDED" in payment_statuses:
        return "REFUNDED"
    if "FAILED" in payment_statuses:
        return "FAILED"
    return "UNPAID"
