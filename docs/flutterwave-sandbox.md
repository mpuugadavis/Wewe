# WEWE Flutterwave sandbox setup

This integration uses Flutterwave's v3 API and Uganda mobile-money charge flow. Keep WEWE in sandbox mode until the end-to-end tests below pass.

## Environment

Set these values in your local `backend/.env` (do not commit that file):

```dotenv
PAYMENT_MODE=EXTERNAL
FLUTTERWAVE_ENVIRONMENT=SANDBOX
FLUTTERWAVE_SECRET_KEY=FLWSECK_TEST-your-test-secret-key
FLUTTERWAVE_WEBHOOK_SECRET_HASH=your-long-random-sandbox-webhook-hash
FLUTTERWAVE_REDIRECT_URL=http://localhost:5500/
FLUTTERWAVE_API_BASE_URL=https://api.flutterwave.com/v3
```

Get the secret key from the Flutterwave dashboard while **Test Mode** is selected. Configure the same webhook secret hash in Flutterwave's test-mode webhook settings. Never put the secret key or webhook hash in frontend JavaScript, Git, screenshots, or chat.

Do not switch `FLUTTERWAVE_ENVIRONMENT` to `LIVE` or use live credentials during sandbox testing. The configuration rejects test keys in live mode and rejects sandbox payment mode in production.

## Webhook configuration

Configure a publicly reachable HTTPS webhook URL in Flutterwave Test Mode:

`https://YOUR_PUBLIC_API_HOST/api/v1/payments/flutterwave/webhook`

Flutterwave cannot reach `localhost` on your laptop. For local end-to-end testing, expose the API through a trusted HTTPS development tunnel and use that tunnel URL in the Flutterwave dashboard. Do not use a temporary tunnel URL in production.

The webhook checks the `verif-hash` header, verifies the transaction with Flutterwave's API, then checks the transaction ID, WEWE payment reference, UGX currency, exact expected amount, and provider status before updating the payment. Duplicate events are handled through WEWE's payment-event protections.

## Sandbox test checklist

1. Start the backend with `PAYMENT_MODE=EXTERNAL` and test credentials only.
2. Place a low-value test order and try MTN Mobile Money, then Airtel Money.
3. Confirm the hosted checkout link opens over HTTPS and uses the selected network.
4. Complete a sandbox payment and verify that WEWE only marks it paid after authoritative server-side verification.
5. Test a failed/cancelled payment, a repeated webhook, and a delayed webhook.
6. Confirm a forged webhook, wrong secret hash, wrong reference, wrong currency, and mismatched amount cannot mark an order paid.
7. Check the payment record and backend logs for errors without logging credentials.
8. Return `PAYMENT_MODE=DISABLED` when you are not actively testing payments.

A browser redirect alone is not proof of payment. Never manually mark a test or live order as paid based only on the checkout page.
