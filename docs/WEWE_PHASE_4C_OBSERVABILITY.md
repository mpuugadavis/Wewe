# WEWE Phase 4C — Logging, Observability and Alerting

## Implemented

- Application logs are emitted as one JSON object per line.
- Every API response carries an X-Request-ID, and the same identifier is included in application request logs.
- API request logs record method, path, HTTP status and duration in milliseconds.
- Unexpected API exceptions are logged with their request ID and exception details.
- Notification-worker failures are logged with stack traces and the worker continues polling.
- Log output goes to stdout so Docker, Kubernetes or a managed container platform can collect it without application-managed log files.
- LOG_LEVEL controls application verbosity and defaults to INFO.
- Logs intentionally exclude query strings, authorization headers, request bodies, phone numbers, email addresses, payment credentials and provider webhook signatures.

## Operational signals

The minimum signals to monitor from collected logs are:

- status_code >= 500: API/server failures.
- Repeated status_code == 503: dependency/provider/configuration availability problems.
- Repeated payment webhook 401/409: signature or payment-event integrity problems requiring investigation.
- Repeated notification-worker polling failures: outbox processing or database problems.
- Sustained high duration_ms: application or dependency latency.

The application does not yet depend on a hosted metrics or alerting vendor. Alert rules should be configured in the deployment/logging platform after infrastructure is selected.

## Safety boundary

This observability slice does not add payment-provider adapters, sandbox adapters, provider credentials or customer cash payments. It also does not change payment state-transition logic.
