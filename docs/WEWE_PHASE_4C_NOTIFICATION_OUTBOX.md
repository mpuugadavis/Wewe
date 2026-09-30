# WEWE Phase 4C — Notification Outbox Processing

This slice adds a durable worker for the existing database-backed notification outbox.

## What is implemented

- notification_outbox jobs now record locked_at and last_error.
- A dispatch index covers status + available_at.
- PostgreSQL workers claim jobs with row locking and SKIP LOCKED, allowing multiple workers to operate without claiming the same pending row.
- Jobs move through PENDING -> PROCESSING -> SENT.
- Retryable failures move to FAILED with exponential backoff.
- Jobs that exceed the configured attempt limit move to DEAD.
- A stale PROCESSING job is reclaimable after the lock timeout.
- A stale job that has already exhausted its attempts is safely dead-lettered instead of remaining stuck forever.
- The current IN_APP channel is acknowledged by the worker because the notification row itself is the durable in-app record consumed by the API.
- No email, SMS, push, or payment-provider adapter is introduced in this slice.

## Running the worker

From backend/:

    python -m app.notification_worker --once

For continuous polling:

    python -m app.notification_worker --interval 5

Useful controls:

- --batch-size 50
- --stale-after 300
- --max-attempts 8

The worker intentionally uses the existing DATABASE_URL configuration and SessionLocal.

## Reliability boundary

Claiming is transactional and bounded. Delivery happens after the claim transaction is committed, so a slow notification handler does not hold database row locks.

Future external channel handlers must be idempotent. If a process crashes after an external provider accepts a notification but before WEWE records SENT, the job may be retried. Provider adapters must therefore use a stable notification ID as their idempotency key where the provider supports it.

## Deferred

- SMTP/email provider
- SMS provider
- push notifications
- provider-specific delivery receipts
- queue infrastructure such as Celery/RQ
- managed scheduler/container orchestration
- production alerting for dead-letter volume

Those belong to later operational/deployment work.
