# WEWE Phase 11 — Cancellation & Refund Lifecycle

## Scope

Phase 11 closes the gap between order cancellation and online-payment refund accounting.

### Implemented

- Cancelling an order with a successful online payment now creates an idempotent, full-amount refund reservation.
- Refund reservations use a deterministic cancellation/payment key, preventing duplicate refund requests if cancellation is retried.
- The order remains `PAID` until the refund is actually confirmed; WEWE never marks money refunded merely because an order was cancelled.
- Customers can see refund records and their status in the order and payment responses.
- The existing admin refund-confirmation workflow now reuses a previously reserved cancellation refund instead of attempting to create a second refund.
- Refund confirmation remains auditable through `PaymentEvent` and `AuditLog`.
- Existing provider webhook refund handling and refund-balance protections remain intact.
- WEWE remains strictly online-payment-only; no cash payment capability is introduced.

## Operational flow

1. Customer cancels an eligible order before physical pickup.
2. If a payment is already `SUCCESSFUL`, WEWE reserves the captured amount as `SUBMITTED`.
3. A `REFUND_PENDING` notification is queued.
4. An authorized operator executes the refund through the configured payment-provider process.
5. The operator confirms the provider reference through the existing admin endpoint.
6. The refund becomes `CONFIRMED`; once the full captured payment has been refunded, the payment becomes `REFUNDED` and the order payment projection updates accordingly.

## Safety rules

- Refunds cannot exceed the captured payment balance.
- `SUBMITTED` and `UNKNOWN` refunds reserve balance until resolved.
- A successful cancellation never silently writes `REFUNDED`.
- Duplicate cancellation requests cannot create duplicate refund reservations.
- A provider refund event remains idempotent and conflict-detectable.
- Successful provider captures arriving after cancellation remain subject to reconciliation/manual review.

## Production boundary

Actual provider-side refund execution is intentionally separated from database state transitions. This prevents WEWE from claiming a refund succeeded when the external mobile-money provider has not confirmed it.