# WEWE Phase 4B — Payment Sandbox

## Purpose

Phase 4B is the online-payment integration phase. WEWE remains **online-payment-only**: customer checkout exposes only MTN Mobile Money and Airtel Money.

This repository now includes a deterministic, no-money simulator for both payment methods. It exercises the same payment-provider boundary used by real adapters without calling a mobile-money network.

The simulator is deliberately the default for local development and tests.

## Payment modes

Set `PAYMENT_MODE` in `backend/.env`:

- `SIMULATED` — safe local/test mode. Both MTN_MOMO and AIRTEL_MONEY are registered as deterministic simulated providers.
- `EXTERNAL` — reserved for provider adapters after provider credentials, callback requirements, and capabilities have been verified.
- `DISABLED` — no payment provider is registered; checkout fails closed with provider-unavailable.

`SIMULATED` is forbidden when `APP_ENV=production`.

## What the sandbox proves

The local sandbox covers:

1. online-only payment method validation;
2. payment attempt creation;
3. immutable attempt references;
4. client idempotency keys;
5. duplicate idempotent replays;
6. pending payment state;
7. signed callback verification;
8. amount/currency/reference matching;
9. successful and failed terminal outcomes;
10. duplicate callback handling;
11. conflicting callback detection;
12. order payment-status aggregation;
13. reconciliation records for uncertain outcomes;
14. late success on a cancelled order without reopening the order;
15. retry blocking while an attempt is pending or unknown.

No customer money is moved by the simulator.

## Testing a callback manually

After creating a payment in simulated mode, obtain its `provider_reference` from the API response. The callback payload is:

```json
{
  "provider_reference": "SIM-MTN_MOMO-...",
  "provider_event_id": "sandbox-event-001",
  "amount_ugx": 27500,
  "currency": "UGX",
  "status": "SUCCESSFUL"
}
```

The callback must be signed with the same HMAC secret used by the local provider. The automated regression suite demonstrates this exact flow.

Do not expose the development `SECRET_KEY` or `PAYMENT_WEBHOOK_SECRET`.

## Real provider onboarding boundary

The simulator must not be mistaken for provider certification.

### MTN MoMo

MTN's official sandbox requires a developer account, a subscribed product, sandbox API user/API key provisioning, and a subscription key. Request-to-Pay is asynchronous: initiation returns an accepted response, the customer authorizes the payment, and the provider sends a final callback. MTN also recommends status polling because callbacks are sent only once.

MTN's published sandbox documentation currently describes EUR as the sandbox test currency. Therefore WEWE must **not** silently convert UGX order totals into EUR merely to make a sandbox call succeed. A Uganda-specific MTN sandbox configuration must be verified before an external MTN adapter is enabled.

### Airtel Money

Airtel Africa provides a developer portal with Uganda selected as an available operating country. Provider credentials and the exact collection/callback capabilities must be verified in the Airtel portal before enabling the external adapter.

## Production gate

Phase 4B is not a production-payment approval. Before `PAYMENT_MODE=EXTERNAL` is enabled for real customers, WEWE still needs:

- provider onboarding/KYC and merchant credentials;
- verified Uganda collection endpoints and authentication;
- verified callback format and authenticity mechanism for each provider;
- provider status-query implementation for reconciliation;
- provider-specific timeout and ambiguous-outcome behavior;
- provider-specific idempotency/reference semantics;
- provider fee/settlement terms;
- verified refund capability before any automated refund is enabled;
- public HTTPS callback endpoints;
- monitoring and alerting for unresolved payments;
- PostgreSQL concurrency tests;
- end-to-end sandbox evidence for each provider;
- a production credential/secrets rotation procedure.

## Important safety rule

Never make a simulated success mean that real money was collected. The authoritative payment state is changed only by the existing payment event/reconciliation machinery after a validated provider outcome.

Cash remains out of scope.
