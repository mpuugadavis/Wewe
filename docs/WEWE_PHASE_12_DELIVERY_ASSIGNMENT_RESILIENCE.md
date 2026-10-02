# WEWE Phase 12 — Delivery Assignment Resilience

## Scope
Phase 12 hardens rider operations around an accepted delivery that cannot be completed by the currently assigned rider.

### Implemented
- An accepted delivery can be released before pickup.
- The existing assignment is returned to UNASSIGNED rather than creating a second assignment.
- The previous rider is detached from the assignment and returned to AVAILABLE.
- The dispatch queue is immediately advanced so another verified, available rider can receive an offer.
- Riders can release their own accepted assignment before pickup.
- Admins can release an accepted assignment when operational intervention is required.
- A DeliveryEvent records every release.
- No delivery earning is created by a release, so releasing and redispatching cannot create a duplicate delivery payout.
- Once pickup has occurred, release is blocked.
- The one-assignment-per-fulfillment database invariant is preserved.

## Lifecycle
UNASSIGNED → ACCEPTED → UNASSIGNED → ACCEPTED → PICKED_UP → OUT_FOR_DELIVERY → DELIVERED

The ACCEPTED → UNASSIGNED transition is deliberately limited to the pre-pickup stage.

## Safety
- No second delivery assignment is created for the same fulfillment.
- A rider cannot release a delivery after pickup.
- The previous rider's active-delivery lock is cleared before redispatch.
- Dispatch still applies the existing verified/available/fresh-location/active-assignment checks.
- Delivery earnings remain tied to the assignment and only arise from the existing completion flow.

## Product boundary
This phase does not introduce automatic rider reassignment after pickup, multi-rider payout splitting, or a new payout policy. Those require explicit custody and compensation rules.