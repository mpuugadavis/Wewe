# WEWE Phase 4B — Payment Core

## Scope

Phase 4B hardens WEWE's online-payment lifecycle without enabling a real-money provider and without shipping provider sandbox adapters.

Customer payment methods are limited to:

- MTN Mobile Money (MTN_MOMO)
- Airtel Money (AIRTEL_MONEY)

Cash is not a supported payment method.

## Implemented core controls

- Payment attempts have immutable internal attempt references.
- Client idempotency keys are unique and replay-safe.
- A second payment attempt is blocked while an existing attempt is PENDING, UNKNOWN, or SUCCESSFUL.
- Provider initiation failures are represented as UNKNOWN; WEWE does not guess whether money moved.
- Provider callbacks are matched to the payment reference, amount, currency, provider, and provider event ID.
- Duplicate provider events are idempotent.
- Conflicting provider events are recorded for review instead of overwriting terminal payment state.
- Authoritative reconciliation can resolve UNKNOWN payments.
- A late successful capture on a cancelled order does not reopen the order and is recorded for manual review.
- Refund reservations cannot exceed the captured payment balance.
- Database-level payment-method enforcement rejects newly inserted or updated non-online payment methods.
- The default development/test payment mode is DISABLED, so a provider cannot be accidentally simulated or charged without explicit configuration.
- Existing Phase 3 migrations remain immutable; the online-payment constraint is introduced by migration 0011.

## Provider boundary

The provider registry remains deliberately separate from payment business logic.

EXTERNAL is not a claim that MTN or Airtel is ready for production. A provider must be explicitly registered only after its Uganda collection API, authentication, callback authenticity, status-query behavior, idempotency/reference rules, currency, timeout semantics, and refund capabilities have been verified.

No provider credentials are committed to the repository.

## Legacy cash records

The PostgreSQL migration adds the online-only payment check as NOT VALID. This is intentional: PostgreSQL can enforce the constraint for all new and updated rows without blocking migration on historical records. Historical cash rows, if any, must be reviewed and resolved before the constraint is validated. The migration never silently rewrites a historical payment into a different payment method.

## Remaining Phase 4B verification

Before Phase 4B is declared closed:

1. Run the complete automated suite.
2. Run the suite against PostgreSQL 16.
3. Exercise concurrent payment-attempt creation against the same order and verify that only one attempt can become active.
4. Verify migration 0011 on a PostgreSQL database containing no unsupported legacy rows.
5. Review any legacy cash rows before validating ck_payment_method_online_only.
6. Verify Docker startup and alembic upgrade head.
7. Keep real provider adapters, provider sandboxes, credentials, OAuth/token flows, and production callbacks deferred until provider onboarding is complete.

## Explicitly deferred

- MTN production adapter
- Airtel production adapter
- MTN/Airtel provider sandbox adapters
- Provider OAuth/token implementation
- Provider-specific callback authenticity implementation
- Provider-specific status polling implementation
- Real-money collection
- Production payment credentials

These are provider-onboarding work, not assumptions hidden inside the Phase 4B core.
