# WEWE

Campus marketplace with a FastAPI/PostgreSQL backend and a responsive storefront. Includes retailer inventory, PawaPay sandbox checkout, OpenRouteService delivery pricing, rider dispatch, handover codes and R2 media.

## Start here

- **Free public sandbox, no purchased domain:** [deployment guide](docs/FREE_DEPLOYMENT.md), using the root `render.yaml`.
- **Existing local sandbox:** http://localhost:8088 — [local setup and checks](docs/SANDBOX_PREVIEW.md).
- **Backend/API development:** [backend README](backend/README.md).
- **Self-hosted multi-service setup:** `compose.preview.yaml`; this requires a host and hostname, unlike the free Render setup.
- **Brand assets:** [SVG logo family](frontend/assets/brand/README.md).

## Repository layout

| Directory | Purpose |
| --- | --- |
| `backend/app` | API, commerce services, workers and explicit setup utilities |
| `backend/migrations` | The authoritative Alembic migration history; do not delete applied migrations |
| `backend/tests` | Integration and business-rule regression tests |
| `frontend` | Active storefront, styles, SVG branding and browser tests |
| `deploy` | Free-host container and graceful process supervisor |
| `docs` | Current deployment guides and historical design/operational decisions |

Runtime dependencies are pinned in `backend/requirements.lock` for Python 3.12 Linux. `pyproject.toml` defines supported ranges. Upgrade the lock deliberately and rerun tests. Local secrets, backups, browser artifacts and generated caches are ignored and excluded from deployment images.

The free deployment is a sandbox with sleep and quota limits. Do not advertise it as a continuously available live-money delivery service. Existing production safeguards remain enabled for `APP_ENV=production`.
