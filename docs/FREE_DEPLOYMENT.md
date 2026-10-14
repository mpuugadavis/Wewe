# Free WEWE sandbox without a domain

This setup prepares a public testing site. It does not create cloud resources, sign up for accounts, move the local database, or enable real-money payments automatically. No paid resources are declared in `render.yaml`.

## Services and limits

| Need | Free choice | Constraint |
| --- | --- | --- |
| Website, API and dispatch/email process | One Render Free web service | Receives an HTTPS `onrender.com` address. Sleeps after 15 minutes without inbound traffic; cold starts and monthly quotas apply. |
| Database | Neon Free PostgreSQL | Keep the Free plan. Compute, storage and transfer quotas apply; use the allowance displayed in your account. Database polling consumes compute while the app is awake. |
| Email | Existing Brevo Free account, HTTPS API | 300 sends/day. Use a verified sender. API keys are different from SMTP passwords. Delivery may be delayed by limits or recipient filtering. |
| Product/profile photos | Existing Cloudflare R2 free allowance | Standard storage includes 10 GB-month, 1 million Class A and 10 million Class B operations/month. R2 is metered beyond its allowance, not an unlimited zero-bill product. Monitor usage and stop uploads before exceeding it. |
| Routing | Existing OpenRouteService Standard key | Free API quotas apply. Leave optional Google Maps keys unset to avoid a billed maps dependency. |
| Payments | Existing PawaPay sandbox | Test transactions only; live payment processing is not promised to be free. |
| Domain and HTTPS | Render-provided address/certificate | No domain purchase or DNS changes needed. |

Sources checked 14 October 2026: [Render Free](https://render.com/docs/free), [Neon Free](https://neon.com/docs/introduction/free-tier), [Brevo Free limits](https://help.brevo.com/hc/en-us/articles/208580669-FAQs-What-are-the-limits-of-the-Free-plan), [R2 pricing](https://developers.cloudflare.com/r2/pricing/), [OpenRouteService](https://openrouteservice.org/services/).

For a strict zero-cost test: do not upgrade plans, add paid workers/databases, purchase email credits, or enable paid auto-recharge. Set provider spend limits where offered. R2's free allowance is not a hard spending cap. This repository cannot guarantee a zero invoice if provider quotas are exceeded. Stop the sandbox before exhausting any allowance.

## Why this differs from the local stack

Render Free blocks SMTP ports and does not provide a free always-on worker. The container therefore serves the storefront and API together, runs the existing notification/dispatch process while the web service is awake, and sends Brevo email over HTTPS. It uses one API process and in-memory rate limits, which reset on restart. The media cleanup worker is intentionally not run; cleanup remains dry-run by default and must be handled as a supervised maintenance task. Production Redis and separate-worker safeguards are unchanged.

Sleeping suspends dispatch and email processing. Rider locations must be refreshed after wake-up. A payment callback can wake the service, but a cold start can exceed provider timeouts; existing payment-status reconciliation remains necessary. Do not use artificial keep-alive traffic to evade hosting limits. A continuously available commercial delivery service needs different hosting resources.

## Setup

1. Keep the existing local database and backups intact. Create a separate Neon **Free** project in a nearby European region. Copy its **direct** PostgreSQL connection URL with `sslmode=require`; keep it private. The launcher converts `postgresql://` to the installed psycopg driver. Never point the free preview at a live production database.
2. In Brevo, verify a sender you control and create an API key. A verified email address can be used for initial testing without buying a domain; delivery/reputation restrictions still apply. Do not use the SMTP login or SMTP password as the API key.
3. In Render, create a Blueprint from `mpuugadavis/Wewe`, selecting the branch containing this file. The Blueprint contains exactly one **Free** web service. Do not add Render's free PostgreSQL database: it expires after 30 days. Automatic deploys are off to avoid unnecessary builds; deploy deliberately after reviewed updates.
4. Fill only the private values requested by Render: `DATABASE_URL`, `BREVO_API_KEY`, `EMAIL_FROM`, `PAWAPAY_API_TOKEN` (sandbox), `OPENROUTESERVICE_API_KEY`, and the four private R2 fields (`STORAGE_BUCKET`, `STORAGE_ENDPOINT`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`; the provider is already S3). Use a separate preview bucket if you later operate production. No secrets belong in Git.
5. Render supplies `RENDER_EXTERNAL_HOSTNAME`; the launcher derives the exact trusted host, CORS origin and callback URLs. No guessed hostname is embedded in code. After deployment, register the resulting checkout/deposit/payout/refund callback URLs in PawaPay wherever its sandbox requires them. Paths are `/api/v1/payments/pawapay/<type>-callback`.
6. Every startup applies committed migrations before starting the API. It never seeds sample accounts or resets passwords. A new database is empty except for data introduced by the existing migrations.

## First administrator and catalogue

Free Render instances do not provide an interactive shell. Build the same image locally:

```powershell
docker build -f deploy/Dockerfile -t wewe-free-preview:local .
```

Create a private, Git-ignored `backend/.env.free` containing the same new sandbox configuration as Render (including the new Neon database URL and generated SECRET_KEY). Then run the one-time administrator setup against that database:

```powershell
docker run --rm -it --env-file backend/.env.free wewe-free-preview:local python -m app.bootstrap_admin --email YOUR_REAL_EMAIL
```

Use `postgresql+psycopg://` in this local file because this direct command bypasses the launcher. The tool prompts privately for a password of at least 16 characters and refuses to create a second administrator or promote an existing account. Use a unique password, not the shared local demo password. Configure campuses, delivery points, categories and retailers through the admin API/dashboard. Do not run the legacy development seed on a public environment.

If you deliberately need sample listings after creating a campus, `python -m app.seed_catalog` adds labelled demo listings only. It generates private random retailer passwords and does not create orders or successful payments. Existing local demo credentials are not copied to the new database.

## Verification before inviting testers

- `/health/ready` responds successfully; the catalogue page loads over HTTPS.
- Register a test customer with a real email, then verify a test shop and rider. Check dashboard notices and real email delivery.
- Upload a profile/product image and confirm it can be viewed after restarting the service.
- Complete a PawaPay sandbox payment, ready the order, make an approved rider available with fresh GPS, accept the nearest-rider offer, and receive the customer handover code.
- Confirm a wrong code cannot complete the delivery and a rider cannot accept a second active assignment.
- Test sleep/wake behavior and explain possible delays to testers. Check provider quota dashboards regularly.
- Export database backups to your own computer using the existing backup scripts. Do not assume the free database plan supplies the recovery guarantees of a paid service.

## Cleanup performed

Removed the unused old homepage backup, old raster logo and duplicate migration outside Alembic's configured `migrations` directory. Retained all active migrations, tests, integration adapters, source artwork, local backups and historical operational documentation. Added an allowlist-only deployment build context, reproducible runtime pins, HTTPS email support, safe first-admin setup and sanitised validation logging. The local SMTP setup continues to work unchanged.

## Repository validation

305 backend tests passed with two opt-in checks skipped; the additional first-admin guard test passed separately (306 passing tests total). Frontend smoke checks and the official Render Blueprint JSON schema passed. The exact deployment image built with locked dependencies and passed `pip check`. A disposable PostgreSQL database migrated successfully, and the container served the homepage, SVG branding, categories API and readiness endpoint; private configuration and removed backup files returned 404. No live cloud resource or real email was created during these checks.
