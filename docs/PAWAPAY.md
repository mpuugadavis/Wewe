# PawaPay integration

WEWE uses PawaPay Merchant API v2 for Uganda mobile-money collections.

## Sandbox configuration

Set these values in the backend `.env`:

```env
PAYMENT_MODE=EXTERNAL
PAYMENT_PROVIDER=PAWAPAY
PAWAPAY_API_TOKEN=<sandbox-token>
PAWAPAY_API_BASE_URL=https://api.sandbox.pawapay.io
PAWAPAY_ENVIRONMENT=SANDBOX

PAWAPAY_DEPOSIT_CALLBACK_URL=https://<public-api-host>/api/v1/payments/pawapay/deposit-callback
PAWAPAY_PAYOUT_CALLBACK_URL=https://<public-api-host>/api/v1/payments/pawapay/payout-callback
```

Never commit the API token.

## Callback URLs

For the current ngrok development tunnel, replace `<public-api-host>` with the active HTTPS ngrok hostname.

Deposit callback:

`POST https://<public-api-host>/api/v1/payments/pawapay/deposit-callback`

Payout callback:

`POST https://<public-api-host>/api/v1/payments/pawapay/payout-callback`

The callback endpoints are intentionally unauthenticated because PawaPay calls them server-to-server. The deposit endpoint validates the JSON structure, deposit ID, terminal status, UGX amount, payment reference, idempotency, and order/payment state before a payment can become successful.

## Payment flow

1. WEWE creates a local Payment with PENDING.
2. WEWE generates a UUIDv4 PawaPay depositId.
3. WEWE calls POST /v2/deposits.
4. ACCEPTED means the request was accepted for processing; it does not mean the customer has paid.
5. PawaPay sends the final callback.
6. COMPLETED becomes SUCCESSFUL; FAILED becomes FAILED.
7. The existing WEWE payment allocation and retailer payable logic runs only after the successful callback.
8. The frontend polls the WEWE payment endpoint while waiting for the asynchronous result.

## Uganda providers

- MTN_MOMO -> MTN_MOMO_UGA
- AIRTEL_MONEY -> AIRTEL_OAPI_UGA

PawaPay expects the payer phone number in MSISDN format, for example 256700000000.

## Production

Before going live, enable and verify PawaPay callback signatures and use the production API base URL:

https://api.pawapay.io

The production callback URLs must be HTTPS and publicly reachable. Do not use localhost.