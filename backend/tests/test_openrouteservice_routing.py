from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import routing


def _settings():
    return SimpleNamespace(
        routing_base_url=None,
        routing_timeout_seconds=5.0,
        routing_user_agent="WEWE-test/1.0",
    )


def test_openrouteservice_route_distance_uses_server_auth_and_road_distance():
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers.get_content_charset.return_value = "utf-8"
    response.read.return_value = b'{"routes":[{"summary":{"distance":3725.4,"duration":841.2}}]}'

    with patch.object(routing, "get_settings", return_value=_settings()), patch.object(
        routing, "urlopen", return_value=response
    ) as mocked_urlopen:
        provider = routing.OpenRouteServiceRoutingProvider(
            "test-ors-key",
            base_url="https://api.example.test/openrouteservice",
        )
        result = provider.route_distance(
            routing.GeoCoordinate.from_values("-0.3376", "32.5680"),
            routing.GeoCoordinate.from_values("-0.3441", "32.5747"),
        )

    request = mocked_urlopen.call_args.args[0]
    assert request.full_url.endswith("/v2/directions/driving-car")
    assert request.get_header("Authorization") == "test-ors-key"
    assert result.provider == "OPENROUTESERVICE"
    assert result.source == "OPENROUTESERVICE_DIRECTIONS"
    assert result.distance_km == Decimal("3.725")
    assert result.reference == "duration_seconds=841.2"


def test_openrouteservice_rejects_missing_route():
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers.get_content_charset.return_value = "utf-8"
    response.read.return_value = b'{"routes":[]}'

    with patch.object(routing, "get_settings", return_value=_settings()), patch.object(
        routing, "urlopen", return_value=response
    ):
        provider = routing.OpenRouteServiceRoutingProvider("test-ors-key")
        with pytest.raises(routing.RoutingProviderError, match="No road route"):
            provider.route_distance(
                routing.GeoCoordinate.from_values("-0.3376", "32.5680"),
                routing.GeoCoordinate.from_values("-0.3441", "32.5747"),
            )


def test_openrouteservice_geocodes_feature_coordinates():
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers.get_content_charset.return_value = "utf-8"
    response.read.return_value = (
        b'{"features":[{"geometry":{"coordinates":[32.5747,-0.3441]}}]}'
    )

    with patch.object(routing, "get_settings", return_value=_settings()), patch.object(
        routing, "urlopen", return_value=response
    ) as mocked_urlopen:
        provider = routing.OpenRouteServiceRoutingProvider("test-ors-key")
        point = provider.geocode("Makerere University, Kampala")

    request = mocked_urlopen.call_args.args[0]
    assert "api_key=test-ors-key" in request.full_url
    assert point == routing.GeoCoordinate.from_values("-0.3441", "32.5747")
