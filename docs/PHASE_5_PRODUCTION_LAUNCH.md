# WEWE Phase 5 — Production Launch + Economics

Status: **foundation started**  
Baseline: `main` at `fb6babd6cc708f88a2bd405e059e553d38f50983`

## 1. Production architecture

WEWE production is deliberately split into managed/external infrastructure and stateless application containers:

- **Frontend:** static HTTPS hosting.
- **API:** FastAPI container behind an HTTPS reverse proxy/load balancer.
- **Database:** managed PostgreSQL.
- **Rate limiting:** shared managed Redis/Redis-compatible service.
- **Media:** production S3-compatible object storage.
- **Workers:** notification outbox worker and media cleanup worker.
- **Routing:** OpenRouteService server-side road routing.
- **Payments:** Flutterwave Uganda mobile money; online-payment-only.
- **Webhook:** public HTTPS endpoint at `/api/v1/payments/webhooks/flutterwave`.
- **Observability:** application request IDs, structured logs, health endpoints and durable worker-health state.

The production compose file intentionally does **not** run local PostgreSQL, Redis or MinIO. Those local services remain development infrastructure; production must use managed/external services.

## 2. Production gates

A production deployment is not considered launch-ready until all of these are true:

### Environment
- `APP_ENV=production`
- PostgreSQL is used.
- Redis is used for rate limiting.
- S3-compatible storage is used.
- HTTPS is used for frontend, API and payment callback.
- CORS contains only the real frontend origin(s).
- Trusted hosts contains only real API hosts.
- Secrets are supplied through the deployment secret store, never Git.
- Production API docs/OpenAPI remain disabled by the application production guardrail.

### Payments
- Flutterwave is switched from sandbox to LIVE only after sandbox E2E is accepted.
- Client ID and Client Secret are production credentials.
- Flutterwave webhook secret hash is configured.
- WEWE payment webhook secret is configured.
- Callback/redirect URLs are HTTPS.
- Provider transaction verification remains authoritative.
- No cash payment path is enabled.

### Routing and delivery
- OpenRouteService production key is configured.
- Delivery quotes use server-resolved road distance.
- Existing committed quotes remain immutable.
- Pricing changes affect only new quotes/orders.

### Storage
- Production S3 bucket exists.
- Bucket credentials are scoped to the required bucket.
- Public media URLs use the production storage/CDN endpoint.
- Cleanup is enabled only after a backup/restore test.
- Local MinIO credentials are never reused in production.

### Operations
- API readiness returns healthy.
- Notification worker is healthy.
- Media cleanup worker is healthy.
- Database backup exists and a restore has been verified.
- Payment/webhook failures are observable by request/payment reference.
- A rollback target is known before the first production migration.

## 3. Launch sequence

1. Provision managed PostgreSQL, Redis and S3-compatible storage.
2. Provision the API host and HTTPS certificate.
3. Configure the production environment from `backend/.env.production.example`.
4. Deploy the API image and run Alembic migrations.
5. Start API and both workers.
6. Verify health/readiness and worker health.
7. Deploy the frontend with the production API base URL.
8. Run sandbox payment E2E through the public HTTPS endpoint.
9. Confirm webhook delivery and transaction verification.
10. Switch Flutterwave credentials/environment to LIVE.
11. Repeat a controlled real-payment smoke test with a small amount.
12. Verify order → payment → fulfilment → rider → delivery → settlement flow.
13. Enable routine backups and monitoring.
14. Declare launch only after the production smoke suite passes.

## 4. Economics baseline

The existing technical pricing engine is retained for launch:

`delivery_fee = max(minimum_fee, base_fee + route_km × price_per_km)`

Current approved configuration:

- base fee: **UGX 1,500**
- price per km: **UGX 500**
- minimum fee: **UGX 2,500**
- rounding: **UGX 500**
- maximum normal route: **15 km**
- multi-retailer consolidation discount: **15%**

These are configuration values, not permanent constants. The launch economics work must evaluate affordability and contribution margin before changing them.

### Economic model to finalize

For every order, track:

- gross merchandise value (GMV)
- retailer payable
- WEWE platform revenue
- delivery fee charged
- rider delivery earning
- payment-provider fee
- routing cost
- storage/infrastructure allocation
- refunds/chargebacks
- contribution margin

Do **not** assume delivery fees are platform profit. Delivery economics must separately account for rider payout and route-dependent operating cost.

### Affordability objective

The initial Makerere launch should optimize for repeat student use rather than maximum per-order extraction. Pricing should be tested against realistic student baskets and short campus routes, while retaining enough contribution margin to sustain the platform.

The final pricing decision should therefore be based on a small scenario matrix:

- single-retailer / short route
- single-retailer / medium route
- multi-retailer / short route
- multi-retailer / medium route
- low-value student basket
- typical student basket
- higher-value basket

Any new configuration must be written to `platform_settings`, versioned, auditable and covered by pricing tests before launch.

## 5. Phase 5 implementation order

### 5A — Production foundation
- production environment contract
- production compose
- HTTPS/reverse-proxy contract
- managed service requirements
- deployment/rollback checklist

### 5B — Observability + recovery
- health monitoring
- worker monitoring
- database backup verification
- restore drill
- payment/webhook alerting
- log retention

### 5C — Economics
- model platform/rider/retailer/payment/routing costs
- calibrate delivery pricing
- finalize settlement cadence
- define minimum viable contribution margin
- test affordability scenarios

### 5D — Production switch
- public frontend/API
- Flutterwave LIVE
- production routing
- production storage
- final smoke test
- launch sign-off

## 6. Non-negotiable launch rules

- No cash payments.
- No client-supplied delivery distance.
- No straight-line distance for commercial delivery pricing.
- No production secrets in Git.
- No sandbox credentials in production.
- No HTTP payment callback in production.
- No wildcard CORS in production.
- No local MinIO/PostgreSQL/Redis dependency in production.
- No production launch without a verified database restore.
