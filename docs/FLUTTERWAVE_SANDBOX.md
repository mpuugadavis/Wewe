# WEWE Flutterwave sandbox setup

WEWE uses Flutterwave's Uganda mobile-money charge flow for MTN and Airtel. Keep the integration in sandbox until the full checkout and webhook tests have passed.

## Local configuration

In the ignored local file `backend/.env`, configure the following using **test-mode credentials from your Flutterwave dashboard**. Never commit this file or paste credentials into chat.

```dotenv
PAYMENT_MODE=EXTERNAL
FLUTTERWAVE_ENVIRONMENT=SANDBOX
FLUTTERWAVE_SECRET_KEY=FLWSECK_TEST-your-test-secret
FLUTTERWAVE_WEBHOOK_SECRET_HASH=your-random-webhook-secret-hash
FLUTTERWAVE_REDIRECT_URL=http://localhost:5500/
FLUTTERWAVE_API_BASE_URL=https://api.flutterwave.com/v3
```

The application refuses to start in sandbox mode if the secret key does not look like a Flutterwave test key, and refuses to run sandbox payments when `APP_ENV=production`.

## Flutterwave dashboard

1. Enable test mode and use the test secret key.
2. Set the webhook secret hash to the same value as `FLUTTERWAVE_WEBHOOK_SECRET_HASH`.
3. Configure the webhook URL as `https://YOUR_PUBLIC_API_HOST/api/v1/payments/flutterwave/webhook`.
4. For local testing, expose the local API through a temporary HTTPS tunnel and use that tunnel URL for the webhook. Flutterwave cannot call a private `localhost` address on your computer.
5. Keep the redirect URL set to the frontend URL you use locally; it is a return destination only, not proof of payment.

## Safety behaviour

- The API uses Flutterwave's test secret key for mobile-money charge creation.
- A webhook must include the configured `verif-hash` header.
- The backend fetches the transaction from Flutterwave and checks the transaction ID, internal `tx_ref`, UGX currency, amount format, and final status before applying the event to WEWE's existing payment state machine.
- Duplicate events are handled by WEWE's existing payment-event idempotency protections.
- A browser redirect does not mark an order as paid.

## Local rebuild

After the branch is merged or checked out locally, rebuild the API image and restart it so the new adapter is included. Do not run a live payment until sandbox success, failure, duplicate-webhook, amount-mismatch, and interrupted-payment cases have been tested.
