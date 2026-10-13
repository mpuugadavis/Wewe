# WEWE API

A standalone FastAPI service for the WEWE campus marketplace. The frontend must call this API; it must never connect directly to PostgreSQL. The API defaults to no trusted secrets: set `SECRET_KEY` before importing or running the service.

## Stack

- Python 3.11+
- FastAPI and Pydantic 2 for versioned REST APIs and request validation
- SQLAlchemy 2 and Alembic for relational persistence and schema changes
- PostgreSQL 16 for deployed environments; SQLite is supported for isolated tests and local experiments
- Argon2 password hashing, short-lived signed access tokens, and rotating opaque refresh tokens
- SlowAPI rate limits with configurable storage; production requires shared Redis so limits remain consistent across API workers

The API is mounted at `/api/v1`. OpenAPI docs are at `/docs` outside production mode.

## Run With Docker Compose

1. Copy `.env.example` to `.env` in this directory.
2. Replace `SECRET_KEY`, `PAYMENT_WEBHOOK_SECRET`, `POSTGRES_PASSWORD`, and `WEWE_SEED_PASSWORD` with unique values. Use at least 32 random characters for each secret and at least 12 for the seed password. Do not commit `.env`.
3. Keep the Compose database hostname `postgres` in `DATABASE_URL`.
4. From this directory, run:

```powershell
docker compose up --build
```

Compose waits for PostgreSQL, applies migrations, and starts the API at `http://localhost:8000`. Seed data is deliberately not applied automatically.

## Run Locally With Python

Use Python 3.11 or newer. Create and activate a virtual environment, then install the package and test extras:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

Copy `.env.example` to `.env`, set the required secrets, and point `DATABASE_URL` to a running PostgreSQL instance (use `localhost` as the hostname from the host machine). For a throwaway local database, set `DATABASE_URL=sqlite:///./wewe.db`. Then:

```powershell
alembic upgrade head
$env:WEWE_SEED_PASSWORD = "use-a-unique-development-password"
python -m app.seed
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The seed command refuses to run unless `APP_ENV` is `development` or `test`. It creates fake `.test` accounts and sample catalog, location, order, delivery, payment, and review data. All seeded accounts use `WEWE_SEED_PASSWORD`; example users include `admin@wewe.test`, `amina@wewe.test`, `shop@wewe.test`, `food@wewe.test`, `books@wewe.test`, `rider@wewe.test`, and `rider2@wewe.test`. Never expose seed accounts outside development.

Readiness and liveness checks: `GET /health/ready` and `GET /health/live`.

## Cloudflare R2 Product And Rider Photo Storage

WEWE uses its existing S3-compatible storage driver for Cloudflare R2; no AWS S3 bucket, public bucket policy, or second media provider is necessary. Configure the backend deployment secrets (not the repository) with:

```dotenv
STORAGE_PROVIDER=S3
STORAGE_BUCKET=YOUR_R2_BUCKET_NAME
STORAGE_ENDPOINT=https://YOUR_CLOUDFLARE_ACCOUNT_ID.r2.cloudflarestorage.com
STORAGE_ACCESS_KEY=YOUR_R2_API_TOKEN_ACCESS_KEY_ID
STORAGE_SECRET_KEY=YOUR_R2_API_TOKEN_SECRET_ACCESS_KEY
# Optional: keep empty when the R2 bucket is private; the WEWE API serves images.
STORAGE_PUBLIC_BASE_URL=
MEDIA_MAX_UPLOAD_BYTES=5242880
```

Create an R2 API token scoped to the WEWE bucket with the permissions required for reading, uploading, listing and deleting media objects. Keep credentials only in local `.env` or a production secret store. Do not publish the bucket or expose API keys to the frontend.

Product images are stored under `products/<product-id>/<content-hash>.<ext>`, limited to 12 validated JPEG, PNG, or WebP photos per product. Public catalog image URLs use `/api/v1/products/images/<image-id>?v=<content-hash>` and the API streams the object from R2. Rider and retailer photos are stored under `profiles/<user-id>/<content-hash>.<ext>` and served through `/api/v1/profile-images/<user-id>`. Changing a verified rider's ID photo sends the account back for admin review and sets it offline.

Before public launch, confirm R2 bucket access with `GET /health/ready` and the admin System Health page, then execute the end-to-end journey: retailer creates a product with several images, reorders/removes an image, confirms customer visibility, rider uploads an identification photo, admin approves it, rider goes online, and customer sees the rider photo on assigned-order tracking. Verify the images still load in a browser after restarting the API container. Run `pytest`, `node frontend/smoke.js`, and the Playwright browser suite against the proposed revision.

## Tests

```powershell
python -m pip install -e ".[test]"
pytest
```

The tests use an isolated in-memory SQLite database with foreign-key enforcement and never touch the configured PostgreSQL database. They cover password hashing, public role assignment, auth/role guards, refresh-token rotation, password-reset invalidation, stock reservation, oversell prevention, historical order-price snapshots, and the customer cart. `tests/test_cart_api.py` pins the working cart: retrieval, adding a listing, repeated adds incrementing quantity, quantity updates, removal, clearing, insufficient-stock rejection, unavailable-listing rejection, cross-customer isolation, subtotal calculation, per-cart listing uniqueness, and the customer-only role guard.

```powershell
pytest                                  # the whole suite
pytest tests/test_cart_api.py           # cart regression tests only
```

The suite must pass against SQLite before a migration is applied. Production concurrency behavior should also be tested against PostgreSQL before launch.

## Data Model

- `users` stores credentials, role, activation state, verification timestamps, and a token version. Customer, retailer, and delivery-agent profiles are separate tables.
- Locations are normalized as `universities -> campuses -> halls -> blocks -> delivery_points`. Official pickup points extend delivery points. Private customer room points have an owner and are never returned by public location/catalog routes.
- `products` holds catalog identity and category; `retailer_products` holds each retailer's SKU, price, and active listing state. `inventory` records stock and reservations, with a composite foreign key enforcing retailer/listing ownership. The `PLATFORM` inventory owner type is reserved for future WEWE-owned stock.
- A customer has one persistent cart. Orders contain immutable product name, SKU, retailer, unit-price, quantity, and line-total snapshots. `retailer_fulfillments` split a multi-retailer order into independently managed work. Delivery assignments and delivery events preserve rider assignment and status history.
- Payments contain UGX amount, method, provider, provider reference, and status; callback event IDs are unique for idempotency. No card details are stored.
- Reviews require an order item belonging to that customer and an order in `DELIVERED` state. A unique order-item constraint prevents a second review.
- Notification events are written to `notification_outbox`; the same records currently back in-app notification reads. `audit_logs` record privileged administrative changes.

Important database writes use transactions. Checkout locks the cart, listing, and inventory rows, validates available stock, increments reserved stock, snapshots order lines, creates per-retailer fulfillment, creates delivery assignments where needed, and clears the cart. A unique `(customer_id, idempotency_key)` constraint prevents duplicate orders on retry. Stock moves from reserved to sold only on confirmed delivery/pickup; cancellations and retailer rejections release reservations.

The `0001_initial` revision is frozen explicit DDL. It describes the schema exactly as it exists in the development database and no longer builds itself from `Base.metadata`, so applying it to an empty database reproduces the current schema and the revision history stays reproducible and reviewable.

## Database Migrations

Migrations are the only supported way to change the schema. The rules are not optional:

1. **Never edit an already-applied migration.** Alembic records the revision id, not the file contents, so an edited revision silently diverges from every database that already ran it. `0001_initial` is frozen and must not be edited.
2. **Every schema change gets a new migration.** Create a revision, review it, apply it. Never change a model and rely on `create_all` or manual SQL.
3. **Review autogenerated migrations manually.** `--autogenerate` produces a draft: it does not detect renames, and it can miss check constraints and server defaults while happily rendering column and table drops. Read the whole file and correct it before applying it.
4. **Test migrations against a scratch database before development or production.** Apply the chain to a throwaway database and compare the resulting schema with the expected one before it ever touches real data.
5. **Back up the database before important schema changes.** A dump is what makes a failed migration recoverable.

Create and apply a revision (the API image already contains Alembic and the migration directory):

```powershell
# 1. Back up first (see below).
# 2. Draft the revision from the model changes.
docker compose exec api alembic revision --autogenerate -m "describe change"
# 3. Open the new file under migrations/versions/ and review every line.
# 4. Apply it, then confirm the recorded revision.
docker compose exec api alembic upgrade head
docker compose exec api alembic current
```

`alembic revision` needs `migrations/script.py.mako`. It is committed to the repository for that reason; without it every revision command fails.

Verify a revision on a throwaway database before trusting it:

```powershell
# Create an empty database beside the development one.
docker compose exec postgres psql -U $env:POSTGRES_USER -d postgres -c "CREATE DATABASE wewe_migration_check"

# Apply the whole chain to the scratch database. Use the development credentials and change only
# the database name in DATABASE_URL for this one command.
docker compose exec -e DATABASE_URL="postgresql+psycopg://USER:PASSWORD@postgres:5432/wewe_migration_check" api alembic upgrade head

# Compare the scratch schema with development (psql \d, or information_schema/pg_constraint queries), then remove it.
docker compose exec postgres psql -U $env:POSTGRES_USER -d postgres -c "DROP DATABASE wewe_migration_check"
```

Back up and restore the development database using the repository scripts:

```bash
export DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/DB'
./scripts/backup_database.sh ./backups/wewe-$(date -u +%Y%m%dT%H%M%SZ).dump

export RESTORE_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/EMPTY_RESTORE_DB'
export RESTORE_CONFIRM=YES
./scripts/restore_database.sh ./backups/wewe-YYYYMMDDTHHMMSSZ.dump
```

The restore target must be a new/empty disposable database. The restore script never drops a database and requires explicit confirmation. Backup archives contain application data and must be protected as secrets.

Back up and restore the development database:

```powershell
docker compose exec postgres pg_dump -U $env:POSTGRES_USER -d $env:POSTGRES_DB -Fc -f /tmp/wewe_dev.dump
docker cp <postgres-container>:/tmp/wewe_dev.dump .\backups\wewe_dev.dump
# Restore into an empty database only, never over a live one.
docker compose exec postgres pg_restore -U $env:POSTGRES_USER -d <empty-database> /tmp/wewe_dev.dump
```

Compose runs `alembic upgrade head` on API startup, so a deployment applies pending revisions automatically. Keep a migration compatible with the API version that is still serving traffic during a rollout: add tables and columns first, and remove them in a later revision.

## Authentication And Permissions

- `POST /api/v1/auth/register` allows only `CUSTOMER`, `RETAILER`, or `DELIVERY_AGENT`; clients cannot create admins.
- `POST /api/v1/auth/login` accepts normalized email or E.164 phone plus password.
- `POST /api/v1/auth/refresh` rotates a single-use refresh token. Reuse revokes its token family. `POST /api/v1/auth/logout` revokes the active family. Password reset increments the user token version, invalidating every session.
- `POST /api/v1/auth/password-reset/request` returns a generic response to avoid account enumeration. In development only, it includes a `development_token`. With SMTP configured, email reset and verification tokens are sent by a TLS SMTP adapter. Phone verification and phone-only password recovery require an SMS adapter; production never returns verification tokens in API responses.
- `GET /api/v1/auth/me` returns the authenticated account. `POST /api/v1/auth/verification/request` and `/confirm` manage email/phone verification.
- Inactive, suspended, and deactivated accounts cannot authenticate. Authorization is enforced in API dependencies and on resource ownership checks, not in frontend navigation.

Tokens should be held in memory or a secure server-side session where possible. Do not put refresh tokens in URLs or logs. Access tokens expire in 15 minutes by default; configure expiries through environment settings.

## Main API Surface

| Area | Routes | Access |
| --- | --- | --- |
| Catalog | `GET /categories`, `GET /products`, `GET /products/{id}`, `GET /retailers`, `GET /retailers/{slug}` | Public; only active listings from verified shops |
| Retailer catalog | `GET/POST /retailers/me/products`, `PATCH/DELETE /retailers/me/products/{listing_id}` | Retailer owner; verified for mutations |
| Profiles | `GET/PATCH /users/me/profile`, `GET/PATCH /retailers/me`, `GET/PATCH /deliveries/me/profile` | Matching authenticated role |
| Locations | `GET /locations/universities`, `/campuses`, `/halls`, `/blocks`, `/delivery-points`, `/pickup-points`; customer-owned locations at `/locations/me/delivery-points` | Public hierarchy; private points require owner |
| Cart | `GET /cart`, `POST/PATCH/DELETE /cart/items`, `DELETE /cart` | Customer |
| Orders | `POST /orders`, `GET /orders`, `GET /orders/{id}`, `POST /orders/{id}/cancel`, `POST /orders/{id}/pickup-confirm` | Customer, owner, assigned rider, or admin as appropriate |
| Retailer fulfilment | `GET /retailers/me/fulfillments`, `POST /retailers/me/fulfillments/{id}/{confirm\|reject\|preparing\|ready}` | Owning retailer |
| Delivery | `GET /deliveries/available`, `POST /deliveries/{id}/accept`, `POST /deliveries/{id}/status`, `GET /deliveries/me`, `/history`, `/earnings` | Verified assigned/available agent |
| Payments | `POST /orders/{id}/payments`, `GET /payments/{id}`, signed `POST /payments/webhooks/{provider}` | Customer owner; provider signature for callbacks |
| Reviews / saved items | `POST /reviews`, `GET /products/{id}/reviews`, `GET/POST /wishlist`, `DELETE /wishlist/{product_id}` | Verified purchaser for review; customer for wishlist |
| Notifications | `GET /notifications`, `POST /notifications/{id}/read` | Authenticated recipient |
| Admin | `/admin/metrics`, `/users`, `/retailers`, `/delivery-agents`, `/products`, `/categories`, `/universities`, `/campuses`, `/halls`, `/blocks`, `/delivery-points`, `/pickup-points`, `/deliveries`, `/delivery-earnings`, `/orders`, `/payments`, `/reviews`, `/settings`, `/audit-logs`, `/reports/*` | `ADMIN` only |

All success responses are JSON resources; errors use `{"error":{"code":"...","message":"..."},"request_id":"..."}`. IDs are UUIDs. Pagination is bounded. Money is integer UGX. The API publishes an OpenAPI contract at `/openapi.json` outside production mode.

## Order, Delivery, And Payment Workflow

1. Customer adds retailer listings to a persistent cart; each change checks active retailer/listing state and available stock.
2. Customer submits `POST /orders` with `delivery_method`, an owned/public `delivery_point_id` or an open `pickup_point_id`, and an `Idempotency-Key` header.
3. The transaction reserves stock and creates one fulfillment per retailer. Retailers confirm/reject, then move confirmed work through preparing and ready.
4. A delivery order becomes available to verified, available agents once its retailer fulfillment is ready. Exact destination information is omitted from open jobs and exposed only after that agent accepts. The customer's `ORDER_PLACED` notification includes `delivery_confirmation_codes`, keyed by fulfillment ID; an assigned agent must provide the matching `confirmation_code` when reporting `DELIVERED`. Agents report pickup, out-for-delivery, and delivery; every transition is recorded.
5. A customer confirms retailer pickup with `/orders/{id}/pickup-confirm`. Completed purchases become reviewable.
6. Customer payments are online-only: only MTN Mobile Money and Airtel Money are accepted. No customer cash-payment path exists. Mobile-money methods use `PaymentProviderRegistry`; no MTN/Airtel provider is registered by default, so requests return `503` until a reviewed adapter and credentials are supplied. The selected adapter verifies provider signatures; the normalized callback then checks reference, amount, currency, and event idempotency. A verified callback can record provider refunds, and an admin can record a full external refund at `POST /admin/payments/{payment_id}/confirm-refund` before a retailer changes an already-paid order.

Delivery fees default to UGX 3,500 per retailer fulfilment and can be changed through the audited admin `delivery_fee_ugx` setting. Confirm the pricing and courier payout policy with the business before production; the current delivery earnings ledger allocates the per-fulfilment fee to the completing agent and records it as pending payout.

## Security And Operations

- Argon2 hashes; no plaintext passwords or card data.
- JWT issuer, audience, expiry and session-family validation. Opaque refresh tokens and reset/verification tokens are stored as SHA-256 digests.
- SQLAlchemy bound statements, Pydantic validation, unique/check/foreign-key constraints, request IDs, generic production errors, no request-body logging, strict CORS allow-list, security headers, and sanitized unique-constraint conflicts.
- Authentication, payment, webhook, and delivery-status endpoints are rate-limited. Local development defaults to in-memory limits; production rejects non-Redis rate-limit storage so multiple API workers cannot silently diverge.
- Production requires PostgreSQL and shared Redis rate-limit storage. Set distinct production secrets through a managed secret store. Configure TLS at the proxy, SMTP, provider-specific webhook verification, object storage, SMS/push adapters, backups, database monitoring, and an outbox worker before launch.
- Product image URLs are stored as catalog data; the API does not proxy uploads. URL validation is centralized and database invariants enforce HTTPS URLs, non-negative ordering, and per-product URL uniqueness. A provider-neutral storage contract is ready for a later authenticated object-storage upload flow; user file uploads remain disabled until that provider is selected.

The root `index.html` is an independent visual prototype using local mock state. It is not wired to this API; integrate it by replacing mock data/actions with requests to the versioned API, while keeping all authorization and pricing decisions on this service.
