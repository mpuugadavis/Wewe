# WEWE Phase 4C — Operational Hardening

## Scope

Phase 4C strengthens the production boundary around the Phase 4B payment core. It does not enable real-money providers and does not add provider sandbox adapters.

### Implemented in this slice

- Production requires PostgreSQL through `DATABASE_URL`.
- Production requires shared Redis-backed rate-limit storage.
- Local development and tests may continue to use `memory://`.
- Authentication token refresh and verification confirmation are rate-limited.
- Online payment initiation is rate-limited.
- Provider webhooks are rate-limited with a higher burst allowance suitable for asynchronous callbacks.
- Redis is included in the Phase 4C CI environment so the rate-limit path is exercised against the same shared-storage technology expected in multi-worker deployments.
- Documentation is aligned with the online-payment-only rule; customer cash payment is not supported.
- Structured application logging, request correlation, request timing/status telemetry and operational error logging are implemented.
- PostgreSQL backup archives, safe restore tooling, and CI restore verification are implemented.

## Safety boundary

`PAYMENT_MODE` remains `DISABLED` by default. Phase 4C does not register MTN or Airtel adapters, does not add sandbox adapters, and does not introduce provider credentials.

## Remaining Phase 4C work

1. External notification channels (email/SMS/push) and their provider-specific adapters.
2. Deployment configuration and infrastructure validation.
3. Final production-readiness regression suite.


The durable outbox worker and backup/restore verification are now implemented; provider-specific onboarding remains a later phase.


## Product media/storage hardening — completed

See `docs/WEWE_PHASE_4C_MEDIA_STORAGE.md`. The current catalog remains URL-only; product image URLs are HTTPS-only and bounded, database invariants are enforced, and a provider-neutral storage contract is ready for the later authenticated object-storage implementation. No cloud provider or sandbox adapter was added.


## Authenticated product image uploads — implemented

See `docs/WEWE_PHASE_4C_AUTHENTICATED_MEDIA_UPLOAD.md`. Retailers can now upload validated JPEG/PNG/WebP images through an authenticated listing-owned endpoint when an S3-compatible storage provider is configured. Local development keeps storage disabled by default.