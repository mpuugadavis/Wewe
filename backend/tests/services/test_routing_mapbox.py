from decimal import Decimal

from app.services import routing


def test_mapbox_route_distance_uses_road_distance(monkeypatch):
    class Settings:
        routing_timeout_seconds = 12.0
        routing_user_agent = "test"

    monkeypatch.setattr(routing, "get_settings", lambda: Settings())
    monkeypatch.setattr(
        routing,
        "_get_json",
        lambda *args, **kwargs: {
            "code": "Ok",
            "routes": [{"distance": 879.6, "geometry": "encoded-route"}],
        },
    )

    provider = routing.MapboxRoutingProvider("test-token")
    result = provider.route_distance(
        routing.GeoCoordinate.from_values("0.3351", "32.5686"),
        routing.GeoCoordinate.from_values("0.3348", "32.5724"),
    )

    assert result.provider == "MAPBOX"
    assert result.source == "MAPBOX_ROAD_ROUTE"
    assert result.distance_km == Decimal("0.880")
    assert result.reference == "encoded-route"


def test_mapbox_geocode_converts_lng_lat_to_lat_lng(monkeypatch):
    class Settings:
        routing_timeout_seconds = 12.0
        routing_user_agent = "test"

    monkeypatch.setattr(routing, "get_settings", lambda: Settings())
    monkeypatch.setattr(
        routing,
        "_get_json",
        lambda *args, **kwargs: {
            "features": [
                {
                    "geometry": {
                        "coordinates": [32.5724, 0.3348],
                    }
                }
            ]
        },
    )

    provider = routing.MapboxRoutingProvider("test-token")
    result = provider.geocode("Makerere University")

    assert result is not None
    assert result.latitude == Decimal("0.3348")
    assert result.longitude == Decimal("32.5724")


def test_mapbox_no_route_is_rejected(monkeypatch):
    class Settings:
        routing_timeout_seconds = 12.0
        routing_user_agent = "test"

    monkeypatch.setattr(routing, "get_settings", lambda: Settings())
    monkeypatch.setattr(
        routing,
        "_get_json",
        lambda *args, **kwargs: {"code": "NoRoute", "routes": []},
    )

    provider = routing.MapboxRoutingProvider("test-token")

    try:
        provider.route_distance(
            routing.GeoCoordinate.from_values("0.3351", "32.5686"),
            routing.GeoCoordinate.from_values("0.3348", "32.5724"),
        )
    except routing.RoutingProviderError as exc:
        assert exc.code == "no_route_found"
    else:
        raise AssertionError("Expected Mapbox no-route response to be rejected")
