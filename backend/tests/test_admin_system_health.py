from datetime import timedelta

from fastapi.testclient import TestClient

from app.models import User, WorkerHealth, utcnow
from app.security import hash_password


def _admin_headers(client: TestClient, database):
    admin = User(
        name="Operations Admin",
        email="ops-admin@example.test",
        password_hash=hash_password("strong-admin-password-42"),
        role="ADMIN",
        status="ACTIVE",
    )
    database.add(admin)
    database.commit()
    login = client.post(
        "/api/v1/auth/login",
        json={"identifier": admin.email, "password": "strong-admin-password-42"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_system_health_is_admin_only(client: TestClient, database) -> None:
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Health Customer",
            "email": "health-customer@example.test",
            "password": "strong-customer-password-42",
            "role": "CUSTOMER",
        },
    )
    assert registered.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={
            "identifier": "health-customer@example.test",
            "password": "strong-customer-password-42",
        },
    )
    assert login.status_code == 200

    response = client.get(
        "/api/v1/admin/system-health",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert response.status_code == 403


def test_system_health_reports_workers_and_storage(client: TestClient, database, monkeypatch) -> None:
    from app.config import get_settings

    settings = get_settings().model_copy(update={"storage_provider": "DISABLED"})
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    headers = _admin_headers(client, database)
    now = utcnow()
    database.add_all([
        WorkerHealth(
            worker_name="notification_outbox",
            status="HEALTHY",
            last_started_at=now - timedelta(seconds=30),
            last_heartbeat_at=now,
            last_success_at=now,
            last_processed=4,
        ),
        WorkerHealth(
            worker_name="media_cleanup",
            status="HEALTHY",
            last_started_at=now - timedelta(seconds=40),
            last_heartbeat_at=now - timedelta(seconds=1801),
            last_success_at=now - timedelta(seconds=1801),
            last_scanned=12,
            last_candidates=2,
            last_deleted=1,
        ),
    ])
    database.commit()

    response = client.get("/api/v1/admin/system-health", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] == "DEGRADED"
    assert payload["storage"]["provider"] == "DISABLED"
    assert payload["storage"]["status"] == "DISABLED"
    assert payload["degraded_workers"] == ["media_cleanup"]
    statuses = {worker["worker_name"]: worker["status"] for worker in payload["workers"]}
    assert statuses == {
        "media_cleanup": "STALE",
        "notification_outbox": "HEALTHY",
    }
