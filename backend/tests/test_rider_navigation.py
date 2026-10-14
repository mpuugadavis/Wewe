import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
import pytest
from sqlalchemy import select
from app.models import DeliveryPoint, User
from app.routers.operations import _delivery_view
from app.services import routing
from test_delivery_dispatch import _dispatch_fixture
from test_order_service import _authorization


def test_navigation_uses_saved_stops_and_assigned_rider_only(client, database, fake_routing, monkeypatch):
    assignment, rider, other = _dispatch_fixture(database)
    assert _delivery_view(database, assignment, False)["dropoff"] is None
    assignment.agent_id = rider.id
    assignment.status = "ACCEPTED"
    database.commit()
    headers = _authorization(database, rider)
    calls = []
    def route(origin, destination, *, profile):
        calls.append((origin, destination, profile))
        return {"geometry": {"type": "LineString", "coordinates": [[32.58, 0.34], [float(destination.longitude), float(destination.latitude)]]}, "distance_m": 1200, "duration_seconds": 300, "steps": [{"instruction": "Continue to the destination", "distance_m": 1200}], "provider": "TEST"}
    monkeypatch.setattr(fake_routing, "navigation_route", route, raising=False)
    base = f"/api/v1/deliveries/{assignment.id}/navigation"
    params = {"stop": "pickup", "latitude": 0.34, "longitude": 32.58}
    for stop, point_id in [("pickup", assignment.pickup_point_id), ("dropoff", assignment.dropoff_point_id)]:
        params["stop"] = stop
        response = client.get(base, headers=headers, params=params)
        assert response.status_code == 200, response.text
        point = database.get(DeliveryPoint, point_id)
        assert response.json()["destination"]["latitude"] == float(point.latitude)
        assert float(calls[-1][1].longitude) == float(point.longitude)
        assert calls[-1][2] == "cycling-regular"
    details = client.get("/api/v1/deliveries/me", headers=headers).json()[0]
    assert details["dropoff"]["latitude"] == 0.35
    assert details["pickup"]["longitude"] == 32.5825
    assert client.get(base, headers=_authorization(database, other), params=params).status_code == 404
    customer = database.scalar(select(User).where(User.role == "CUSTOMER"))
    assert client.get(base, headers=_authorization(database, customer), params=params).status_code == 403
    assert client.get(base, params=params).status_code == 401
    for invalid in [{**params, "stop": "arbitrary"}, {**params, "latitude": 91}, {**params, "longitude": "nan"}]:
        assert client.get(base, headers=headers, params=invalid).status_code == 422
    assignment.status = "DELIVERED"
    database.commit()
    assert client.get(base, headers=headers, params=params).status_code == 404


def test_navigation_reports_missing_pin_and_provider_outage(client, database, fake_routing, monkeypatch):
    assignment, rider, _ = _dispatch_fixture(database)
    assignment.agent_id = rider.id
    assignment.status = "ACCEPTED"
    database.commit()
    headers = _authorization(database, rider)
    base = f"/api/v1/deliveries/{assignment.id}/navigation?stop=pickup&latitude=0.34&longitude=32.58"
    def unavailable(*args, **kwargs):
        raise routing.RoutingProviderError("routing_provider_unreachable", "Use Open in maps or retry.")
    monkeypatch.setattr(fake_routing, "navigation_route", unavailable, raising=False)
    assert client.get(base, headers=headers).status_code == 503
    point = database.get(DeliveryPoint, assignment.pickup_point_id)
    point.latitude = None
    point.longitude = None
    database.commit()
    response = client.get(base, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "destination_coordinates_missing"


def test_ors_navigation_geometry_instructions_and_private_key():
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = json.dumps({"features": [{"geometry": {"type": "LineString", "coordinates": [[32.58, 0.34], [32.59, 0.35]]}, "properties": {"summary": {"distance": 1500, "duration": 300}, "segments": [{"steps": [{"instruction": "Turn right", "distance": 120}]}]}}]}).encode()
    provider = routing.OpenRouteServiceRoutingProvider("private-test-key", base_url="https://api.example.test")
    with patch.object(routing, "urlopen", return_value=response) as http:
        result = provider.navigation_route(routing.GeoCoordinate.from_values(0.34,32.58), routing.GeoCoordinate.from_values(0.35,32.59), profile="cycling-regular")
    request = http.call_args.args[0]
    assert request.full_url.endswith("/cycling-regular/geojson")
    assert request.get_header("Authorization") == "private-test-key"
    assert json.loads(request.data)["coordinates"] == [[32.58, 0.34], [32.59, 0.35]]
    assert result["steps"][0]["instruction"] == "Turn right"
    assert result["geometry"]["coordinates"][1] == [32.59, 0.35]
    assert "private-test-key" not in json.dumps(result)
    response.read.return_value = b'{"features": []}'
    with patch.object(routing, "urlopen", return_value=response), pytest.raises(routing.RoutingProviderError):
        provider.navigation_route(routing.GeoCoordinate.from_values(0.34,32.58), routing.GeoCoordinate.from_values(0.35,32.59))
    with patch.object(routing, "urlopen", side_effect=HTTPError("https://example.test",429,"limit",{},None)), pytest.raises(routing.RoutingProviderError, match="Open in maps"):
        provider.navigation_route(routing.GeoCoordinate.from_values(0.34,32.58), routing.GeoCoordinate.from_values(0.35,32.59))
