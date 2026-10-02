# WEWE Phase 14 — Security & Abuse Hardening

Phase 14 adds defense-in-depth protections at the API boundary while preserving existing authentication, authorization, payment, rider and settlement workflows.

## Implemented

- Trusted Host allow-list is configurable through `TRUSTED_HOSTS`.
- Requests with a declared `Content-Length` above `MAX_REQUEST_BODY_BYTES` are rejected with HTTP 413.
- Security response headers include:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - restrictive API `Content-Security-Policy`
  - production HSTS
- Authentication responses are marked `Cache-Control: no-store`.
- Existing SlowAPI rate limiting remains enabled, with Redis required for production.
- Existing role-based authorization and object ownership checks remain the source of truth.
- Payment webhooks continue to require provider signature verification and event/idempotency controls.
- Online-payment-only remains unchanged.

## Production configuration

Set `TRUSTED_HOSTS` to the exact public API hostnames used by the deployment. Do not use a wildcard in production.

Set `MAX_REQUEST_BODY_BYTES` according to the largest legitimate API request. The current default is 2 MB; media uploads remain governed separately by `MEDIA_MAX_UPLOAD_BYTES`.

Use Redis for `RATE_LIMIT_STORAGE_URI` so rate limits are shared across API instances.

## Scope boundary

This phase does not weaken business authorization, introduce cash payments, or silently change payment/refund/settlement behavior. Security controls should be reviewed again after the production topology, reverse proxy and frontend deployment domains are finalized.
