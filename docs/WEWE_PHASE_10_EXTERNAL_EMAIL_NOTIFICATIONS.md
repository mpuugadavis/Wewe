# WEWE Phase 10 — External Email Notifications

## Scope

Phase 10 begins the external notification channel layer using the existing durable PostgreSQL notification outbox and SMTP mail adapter.

### Implemented

- NotificationDispatcher now supports the EMAIL channel.
- Email jobs are delivered by the existing SMTP adapter.
- Email payloads require `to`, `subject`, and `body`.
- Delivery remains asynchronous through the notification worker.
- Provider failures remain retryable and eventually become dead-lettered according to the existing outbox policy.
- No email provider SDK or vendor lock-in is introduced.
- Existing in-app notifications are unchanged.

### Safety boundary

SMTP configuration remains disabled in development unless configured. No notification job can silently report success when an email payload is malformed.

WEWE remains online-payment-only; this phase does not introduce cash payments or payment-provider credentials.

### Production path

Configure the existing SMTP settings in the deployment: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME` (optional), `SMTP_PASSWORD` (optional), and `EMAIL_FROM`.

The worker then processes durable EMAIL outbox jobs independently from API request traffic.
