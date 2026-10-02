# WEWE Phase 15 — Sensitive Business Flow Hardening

## Objective

Phase 15 adds targeted abuse controls to high-impact authenticated business flows. OWASP's API Security Top 10 identifies unrestricted resource consumption and unrestricted access to sensitive business flows as distinct API risks; rate limiting is one control that can reduce automated abuse of these flows. 

## Implemented controls

The existing SlowAPI/Redis rate-limiting infrastructure is retained and extended with explicit endpoint limits:

### Customer commerce
- Delivery quote preview: **20 requests/minute**
- Checkout/order creation: **10 requests/minute**
- Reorder: **10 requests/minute**
- Order cancellation: **10 requests/minute**

### Delivery operations
- Delivery-offer accept: **20 requests/minute**
- Delivery-offer reject: **20 requests/minute**
- Direct delivery assignment accept: **20 requests/minute**
- Accepted-delivery release: **20 requests/minute**
- Delivery status updates remain **10 requests/minute**

These controls are in addition to the existing global limiter and authentication/authorization checks.

## Design constraints

- Limits are keyed through the existing SlowAPI limiter; production configuration continues to require Redis-backed rate limiting.
- No cash-payment flow is introduced.
- No authorization rules are weakened.
- Idempotency remains responsible for preventing duplicate financial operations; rate limiting is an abuse-control layer, not a substitute for idempotency.
- Delivery state transitions remain enforced by the existing state-transition services.
- Existing payment webhook verification and settlement controls are unchanged.

## Verification

The complete backend and operational verification workflows must pass before the phase is merged.

## Reference

OWASP API Security Top 10 2023 identifies:
- API4: Unrestricted Resource Consumption
- API6: Unrestricted Access to Sensitive Business Flows

Source: OWASP API Security Project.
