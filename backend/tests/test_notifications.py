from uuid import uuid4

from fastapi.testclient import TestClient

from app.models import NotificationOutbox


def _user(client: TestClient):
    reg = client.post("/api/v1/auth/register", json={
        "name": "Notification Test User",
        "email": f"notification-{uuid4().hex[:8]}@example.test",
        "phone": f"+2567{str(uuid4().int)[:8]}",
        "password": "strong-password-42",
        "role": "CUSTOMER",
    })
    assert reg.status_code == 201
    login = client.post("/api/v1/auth/login", json={
        "identifier": reg.json()["email"],
        "password": "strong-password-42",
    })
    assert login.status_code == 200
    return reg.json(), {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_notification_list_is_private_and_mark_read_is_idempotent(client: TestClient, database):
    user, headers = _user(client)
    notification = NotificationOutbox(
        user_id=user["id"],
        event_type="ORDER_READY",
        channel="IN_APP",
        payload={"title": "Order ready", "message": "Your order is ready."},
    )
    database.add(notification)
    database.commit()

    response = client.get("/api/v1/notifications?unread_only=true", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["payload"]["message"] == "Your order is ready."

    read = client.post(f"/api/v1/notifications/{notification.id}/read", headers=headers)
    assert read.status_code == 200
    assert read.json()["read_at"]

    again = client.post(f"/api/v1/notifications/{notification.id}/read", headers=headers)
    assert again.status_code == 200
    assert again.json()["read_at"]

    unread = client.get("/api/v1/notifications?unread_only=true", headers=headers)
    assert unread.status_code == 200
    assert unread.json() == []


def test_notification_cannot_be_read_by_another_user(client: TestClient, database):
    owner, owner_headers = _user(client)
    other, other_headers = _user(client)
    notification = NotificationOutbox(
        user_id=owner["id"],
        event_type="ORDER_READY",
        channel="IN_APP",
        payload={"message": "Private notification"},
    )
    database.add(notification)
    database.commit()

    response = client.post(f"/api/v1/notifications/{notification.id}/read", headers=other_headers)
    assert response.status_code == 404

    listed = client.get("/api/v1/notifications", headers=other_headers)
    assert listed.status_code == 200
    assert listed.json() == []
