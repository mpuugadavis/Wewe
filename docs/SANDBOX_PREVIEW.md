# WEWE sandbox preview

## What is included

- Responsive header departments menu with accessible keyboard controls and category filtering, replacing the broken/repeated category photos.
- Verified retailers can select or create a product category inline, describe a product and upload multiple photos. Duplicate category names reuse the existing category; disabled categories cannot be revived by a retailer.
- A repeatable demo catalogue: 28 listings in seven named sample shops, covering all seven departments. Sample shops and descriptions are clearly labelled. No fabricated sales or reviews are added.
- Restored customer handover codes in email and WEWE notifications, required delivery confirmation, and one active assignment per rider.
- Correct delivery totals and consolidation discounts when one retailer's fulfilment is rejected. Existing captured/pending-payment protections remain enforced.
- Payment callback recovery, private live tracking, R2 photos, OpenRouteService and Brevo are preserved.

## Local preview

The updated local preview is available at http://localhost:8088. It uses the existing sandbox API and catalogue (34 products, including 28 demo listings). Both application images were built successfully; the real storefront loaded without browser errors at phone and desktop sizes.

The local database was backed up before adding samples. The catalogue seed only creates its own sample shops/listings; rerunning it adds no duplicates and does not modify orders or payments. It refuses APP_ENV=production.

```powershell
# From backend, with its environment configured:
python -m app.seed_catalog
```

Do not use the demo shops for real sales. Before a live launch, remove or deactivate their `DEMO-` listings and `demo-` shops through the normal administration flow, and provision a separate production database.

## Public sandbox deployment

This package is for a Docker host with a preview hostname. A hosting account and DNS destination have not been chosen in this chat; no public deployment has been made.

1. Copy `backend/.env.preview.example` to `backend/.env.preview` on the host. Keep this file private; it is excluded from Git and Docker build contexts.
2. Set WEWE_DOMAIN to the actual hostname, point its DNS to the host, and permit ports 80/443. Update CORS_ORIGINS, TRUSTED_HOSTS and all PawaPay callback URLs to this HTTPS hostname. Retain localhost and 127.0.0.1 in TRUSTED_HOSTS for health checks.
3. Generate unique PostgreSQL and authentication secrets. DATABASE_URL must use the same PostgreSQL password (URL-encoded), database `wewe_preview`, host `postgres`, and user `wewe`.
4. Configure the PawaPay sandbox token, OpenRouteService key, R2 `wewe` bucket read/write credentials, and Brevo SMTP credentials/sender. Do not paste secrets into Git or chat. Use a separate preview R2 bucket if preview and live environments will coexist. Preview media cleanup is forced to dry-run so a new preview database cannot delete objects belonging to another environment; enable deletion only after isolating the bucket.
5. Start the stack from the repository root:

```sh
docker compose --env-file backend/.env.preview -f compose.preview.yaml config --quiet
docker compose --env-file backend/.env.preview -f compose.preview.yaml up -d --build
```

The stack contains PostgreSQL, Redis, API, migrations, notification and media-cleanup workers, and Caddy. Only the web server publishes ports; API/database/Redis remain internal. Caddy serves the frontend and proxies `/api/*` on the same origin with automatic HTTPS. The preview stack explicitly forces PawaPay SANDBOX and its sandbox API URL. Its database volume is separate from the local development volume.

Migrations run before the application. Configure the campus, public destinations and real retailer pickup points in administration before inviting testers. The catalogue seed requires an existing campus and never creates fake customer accounts, orders or successful payments.

## Verification and operations

- Full backend regression suite: 300 passed, 2 opt-in integration checks skipped. PostgreSQL concurrency and an actual R2 write/read/delete probe passed separately.
- Fresh PostgreSQL migrations reached `0028_one_active_rider_delivery`; payment concurrency verification passed separately.
- Actual R2 object write/read/delete was verified using a temporary diagnostic object.
- Product photography returned HTTP 200 for all seven departments.
- Browser coverage includes category navigation, customer checkout and payment recovery, live tracking, and retailer category creation with two image uploads at phone/tablet/desktop sizes.
- Frontend JavaScript syntax and existing smoke checks pass.

Verify `/health/ready`, check both worker heartbeats in admin, test a sandbox payment and delivery handover, and schedule database backups before opening the preview to testers. A readiness response alone does not prove that email delivery or mobile location permissions work for every tester. Riders must grant location permission and keep WEWE open; use HTTPS on public previews.

The public preview requires the hosting/domain and secret configuration above. This is not a live-money launch configuration.

## Demo image refresh

Run `python -m app.seed_catalog --refresh-demo-images` in the configured non-production backend to replace seed-owned category photos with 28 distinct listing images and remove duplicate-size gallery entries. Retailer-uploaded photos are preserved. Shops without uploaded photos display personalised branded monograms; riders without identification photos display labelled placeholders and still require real approved face photos. No stock portrait is accepted as identification.
