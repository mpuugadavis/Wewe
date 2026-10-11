# Phase 11A — Flutterwave sandbox setup

This implementation uses Flutterwave Standard hosted checkout through the v3 API. It is a sandbox integration foundation; do not switch live credentials on until the acceptance checks below pass.

## Configuration

Set these values in the local `backend/.env` file. Never commit real credentials.

- `PAYMENT_MODE=EXTERNAL`
- `FLUTTERWAVE_SECRET_KEY`: Flutterwave **test** secret key from the Flutterwave dashboard.
- `FLUTTERWAVE_WEBHOOK_SECRET_HASH`: a unique random secret (at least 32 characters) that exactly matches the webhook secret hash configured in Flutterwave.
- `FLUTTERWAVE_API_BASE_URL=https://api.flutterwave.com/v3`
- `PAYMENT_RETURN_URL=http://localhost:5500/?payment=complete` for local development.
- Replace the example `PAYMENT_WEBHOOK_SECRET` with a separate random value of at least 32 characters, as required by the existing application settings.

The API registers Flutterwave for both existing online payment choices only when `PAYMENT_MODE=EXTERNAL` and the Flutterwave key and webhook hash are present. Cash remains unsupported. Flutterwave hosted checkout requires an email; checkout now asks for one when needed.

## Local webhook testing

Flutterwave cannot call `localhost` on your computer. Start the API and expose port 8000 through an HTTPS tunnel, for example:

    ngrok http 8000

Copy the HTTPS forwarding domain shown by ngrok. In Flutterwave Dashboard → Settings → Webhooks, configure this URL, replacing the example domain:

    https://YOUR-NGROK-DOMAIN/api/v1/payments/webhooks/flutterwave

Set the same random secret hash in the dashboard and `FLUTTERWAVE_WEBHOOK_SECRET_HASH` in the backend environment. Enable webhook retries. Restart the API after changing environment variables. Do not expose the API publicly without the webhook signature configured.

The browser return URL and webhook URL are different: `PAYMENT_RETURN_URL` is for the student's browser; the webhook endpoint is called by Flutterwave's servers.

## Verification behavior

- The webhook must have the configured Flutterwave v3 `verif-hash` header.
- Successful and failed `charge.completed` events are verified against Flutterwave's transaction verification API before WEWE applies a payment state change.
- Transaction reference, transaction ID, amount and currency are checked against the provider response and WEWE payment record.
- A verification timeout returns a retryable response rather than marking the order paid.
- Existing payment event deduplication and conflict recording remain in use.

## Acceptance checklist before merging or using live credentials

1. Run `pytest` from the backend directory.
2. Confirm the app starts with `PAYMENT_MODE=DISABLED` and no Flutterwave credentials.
3. Configure test credentials and `PAYMENT_MODE=EXTERNAL`, then restart the backend.
4. Complete a sandbox mobile-money checkout and verify that the browser opens the hosted checkout URL.
5. Confirm a valid webhook changes the payment to `SUCCESSFUL` only after transaction verification.
6. Replay the same webhook and confirm it does not apply the payment twice.
7. Send a webhook with a wrong hash and confirm it is rejected.
8. Confirm mismatched transaction references, amounts or currency never mark an order paid.
9. Test failed, pending, timed-out and duplicate notifications.
10. Keep live credentials disabled until all checks pass.

Official documentation:
- https://developer.flutterwave.com/docs/webhooks
- https://developer.flutterwave.com/docs/transaction-verification
- https://developer.flutterwave.com/docs/flutterwave-standard-1
