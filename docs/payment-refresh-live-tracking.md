# Payment confirmation and customer live tracking

## Changes

PawaPay v2 deposit lookup responses wrap the actual payment state in `data`; the outer `FOUND` value is a lookup outcome. The adapter now validates the wrapper and deposit ID before using the transaction status.

Authenticated customers can refresh their own payments or order payments. These endpoints retrieve PawaPay's authoritative outcome and reuse the callback handler's amount/currency validation, idempotency, allocations, notifications and cancelled-order review. They never initiate another payment. The generic PawaPay webhook also verifies the provider's record instead of trusting client-supplied outcomes.

Checkout checks confirmation every five seconds for up to two minutes. Opening **Track order** also recovers pending confirmations. Customer order cards refresh every five seconds, and tracking continues from waiting for assignment through delivery. Connection failures display a retry message; obsolete modal requests cannot overwrite a newer dialog. Completed deliveries stop polling and hide rider location. Riders obtain a fresh GPS fix every 25 seconds while sharing their location, including when stationary.

PostgreSQL now uses `restart: unless-stopped`, matching the API's local restart policy. No database volumes were removed or replaced.

## Validation

- 18 focused payment and customer-tracking tests pass, including authorization, callback/refresh idempotency, provider failures, amount/currency mismatches, stale GPS and completed-delivery privacy.
- The interrupted dispatch/migration work was separately exercised: 19 tests pass.
- JavaScript syntax and existing frontend smoke checks pass.
- Chrome browser checks at 360, 768 and 1440 pixels cover checkout confirmation, pending-order recovery, unassigned-to-live tracking, temporary outage recovery, stale GPS, delivery completion and responsive layouts.
- A broader order-service run found three failures. Each was reproduced against committed HEAD before this change: agent acceptance/cancellation, cross-retailer rejection/reservation, and a payment-idempotency fixture violating the delivery-price constraint.

## Local rollout

The existing API image was preserved as `wewe-payment-refresh-base:local`. A small overlay containing only the payment router and PawaPay adapter was built and deployed, preserving the existing routing, storage, notification and delivery code. Readiness passed. The source-served frontend uses the updated JavaScript after a browser reload.

Copilot's unrelated configuration, pricing, dispatch/migration and generated-package changes remain in the working tree for separate review; they are not included in this payment/tracking commit.

To rerun the focused tests, use the project's Python environment with `APP_ENV=test`, `DATABASE_URL=sqlite://`, `PAYMENT_MODE=DISABLED`, `OPENROUTESERVICE_API_KEY=test-routing-key` and `PYTHONPATH=backend`:

```powershell
backend/.venv/Scripts/python.exe -m pytest -o addopts='' backend/tests/test_payment_refresh.py backend/tests/test_pawapay_deposit_status.py backend/tests/test_customer_tracking.py -q
node --check frontend/app.js
node frontend/smoke.js
```

The browser script requires Playwright. Set `WEWE_TEST_ENGINE=chromium`, `WEWE_TEST_CHANNEL=chrome`, and `WEWE_TEST_WIDTHS=360,768,1440`, then run `node frontend/responsive.browser.cjs` from the repository root. Browser tests use fixture responses and never initiate real payments.
