# WEWE Phase 13 — Retailer Settlement Operations

Phase 13 exposes the existing settlement ledger lifecycle to the admin operational workspace without inventing commercial payout policy.

## Implemented
- Admins can list retailer settlement instructions.
- Results can be filtered by retailer and settlement status.
- Each settlement includes amount, lifecycle status, payout reference, authorization and timing fields.
- The response includes an auditable line count, line total and balance check from the existing settlement controls.
- No settlement eligibility, cadence, commission, tax or payout amount is inferred by the endpoint.
- Existing idempotent draft creation and lifecycle controls remain the source of truth.
- Online-payment-only remains unchanged.

## Production boundary
Actual payout execution remains an explicit operational action. This phase makes reconciliation visible and queryable; it does not silently trigger money movement.