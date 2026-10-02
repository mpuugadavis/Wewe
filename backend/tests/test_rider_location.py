from fastapi.testclient import TestClient

from app.models import DeliveryAgent


def _register_rider(client: TestClient) -> tuple[dict, dict]:
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Rider Location Test",
            "email": "rider-location@example.test",
            "phone": "+256700123456",
            "password": "strong-rider-password-42",
            "role": "DELIVERY_AGENT",
            "transport_mode": "Bicycle",
        },
    )
    assert registration.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={
            "identifier": "rider-location@example.test",
            "password": "strong-rider-password-42",
        },
    )
    assert login.status_code == 200
    return registration.json(), {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_verified_available_rider_can_publish_location(client: TestClient, database) -> None:
    user, headers = _register_rider(client)
    agent = database.get(DeliveryAgent, user["id"])
    assert agent is not None
    agent.verification_status = "VERIFIED"
    agent.availability_status = "AVAILABLE"
    database.commit()

    response = client.patch(
        "/api/v1/deliveries/me/location",
        json={
            "latitude": 0.3476,
            "longitude": 32.5825,
            "accuracy_m": 8.5,
            "heading_deg": 182.25,
            "speed_mps": 5.2,
        },
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == user["id"]
    assert body["latitude"] == 0.3476
    assert body["longitude"] == 32.5825
    assert body["accuracy_m"] == 8.5
    assert body["heading_deg"] == 182.25
    assert body["speed_mps"] == 5.2
    assert body["updated_at"]

    fetched = client.get("/api/v1/deliveries/me/location", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["latitude"] == 0.3476


def test_rider_cannot_publish_location_while_offline(client: TestClient, database) -> None:
    user, headers = _register_rider(client)
    agent = database.get(DeliveryAgent, user["id"])
    assert agent is not None
    agent.verification_status = "VERIFIED"
    database.commit()

    response = client.patch(
        "/api/v1/deliveries/me/location",
        json={"latitude": 0.3476, "longitude": 32.5825, "accuracy_m": 10},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agent_offline"


def test_rider_location_rejects_invalid_coordinate_pair(client: TestClient, database) -> None:
    user, headers = _register_rider(client)
    agent = database.get(DeliveryAgent, user["id"])
    assert agent is not None
    agent.verification_status = "VERIFIED"
    agent.availability_status = "AVAILABLE"
    database.commit()

    response = client.patch(
        "/api/v1/deliveries/me/location",
        json={"latitude": 95, "longitude": 32.5825, "accuracy_m": 10},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
