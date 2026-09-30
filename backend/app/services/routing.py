"""Road-route distance lookup for WEWE delivery pricing (COM-FEE-004).

WEWE prices delivery from the **actual road route** between a retailer's pickup
location and the customer's delivery location. This module is the only place in
the backend that talks to a mapping/routing service.

Supported providers:

``GOOGLE_MAPS``
    Google Maps Directions API for the route and the Google Geocoding API for
    addresses that have no stored coordinates. Requires ``GOOGLE_MAPS_API_KEY``.

``OSRM``
    The OpenStreetMap OSRM road service for the route (no API key) and the
    Nominatim geocoder for addresses that have no stored coordinates.

Design boundaries (COM-FEE-004 / COM-FEE-009):

* A provider only ever returns a **routed** road distance. There is no
  straight-line/Haversine fallback: when a route cannot be produced the
  provider raises :class:`RoutingProviderError` so checkout can refuse the
  delivery instead of inventing a distance.
* Distances are returned in kilometres with millimetre precision, matching the
  precision the delivery-pricing engine accepts.
"""

import json
import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from app.config import get_settings

logger = logging.getLogger(__name__)

#: Distances are stored with millimetre precision (three decimals of a kilometre).
ROUTE_DISTANCE_QUANTUM = Decimal("0.001")

GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
OSRM_ROUTE_PATH = "/route/v1/driving"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"

#: Values recorded on a committed delivery quote so the priced route stays auditable.
GOOGLE_MAPS_DISTANCE_SOURCE = "GOOGLE_MAPS_DIRECTIONS"
OSRM_DISTANCE_SOURCE = "OSRM_ROAD_ROUTE"


class RoutingProviderError(RuntimeError):
    """A routing or geocoding provider could not produce an answer."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GeoCoordinate:
    """A WGS84 coordinate in decimal degrees."""

    latitude: Decimal
    longitude: Decimal

    def __post_init__(self) -> None:
        if not (-90 <= self.latitude <= 90):
            raise RoutingProviderError("invalid_coordinates", "Latitude must be between -90 and 90 degrees.")
        if not (-180 <= self.longitude <= 180):
            raise RoutingProviderError("invalid_coordinates", "Longitude must be between -180 and 180 degrees.")

    @classmethod
    def from_values(cls, latitude: Any, longitude: Any) -> "GeoCoordinate":
        try:
            lat = Decimal(str(latitude))
            lon = Decimal(str(longitude))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise RoutingProviderError("invalid_coordinates", "Coordinates must be decimal degrees.") from exc
        return cls(latitude=lat, longitude=lon)

    def as_text(self) -> str:
        return f"{self.latitude},{self.longitude}"


@dataclass(frozen=True)
class RouteDistance:
    """One provider's road-route distance between two coordinates."""

    distance_km: Decimal
    #: Recorded as ``delivery_quotes.distance_source``.
    source: str
    #: Provider name, e.g. ``GOOGLE_MAPS`` or ``OSRM``.
    provider: str
    #: Provider route summary/reference when one is returned.
    reference: str | None = None


class RoutingProvider(Protocol):
    name: str
    source: str

    def geocode(self, address: str) -> GeoCoordinate | None: ...

    def route_distance(self, origin: GeoCoordinate, destination: GeoCoordinate) -> RouteDistance: ...


def metres_to_kilometres(metres: Any) -> Decimal:
    """Convert a provider's metre reading into the stored kilometre precision."""

    try:
        value = Decimal(str(metres))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RoutingProviderError(
            "routing_provider_invalid_response", "The routing service returned an unreadable distance."
        ) from exc
    if value < 0:
        raise RoutingProviderError(
            "routing_provider_invalid_response", "The routing service returned a negative distance."
        )
    return (value / Decimal("1000")).quantize(ROUTE_DISTANCE_QUANTUM, rounding=ROUND_HALF_UP)

def _get_json(url: str, *, timeout: float, user_agent: str) -> Any:
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:  # provider endpoints are fixed or configured
            charset = response.headers.get_content_charset() or "utf-8"
            payload = response.read().decode(charset)
    except HTTPError as exc:
        raise RoutingProviderError(
            "routing_provider_error", f"The routing service responded with HTTP {exc.code}."
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RoutingProviderError(
            "routing_provider_unreachable", "The routing service could not be reached."
        ) from exc
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RoutingProviderError(
            "routing_provider_invalid_response", "The routing service returned an unreadable response."
        ) from exc


class GoogleMapsRoutingProvider:
    """Google Maps Directions + Geocoding implementation of the routing contract."""

    name = "GOOGLE_MAPS"
    source = GOOGLE_MAPS_DISTANCE_SOURCE

    def __init__(
        self,
        api_key: str,
        *,
        directions_url: str = GOOGLE_DIRECTIONS_URL,
        geocoding_url: str = GOOGLE_GEOCODING_URL,
        timeout: float | None = None,
        user_agent: str | None = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key
        self._directions_url = directions_url
        self._geocoding_url = geocoding_url
        self._timeout = timeout if timeout is not None else settings.routing_timeout_seconds
        self._user_agent = user_agent or settings.routing_user_agent

    def geocode(self, address: str) -> GeoCoordinate | None:
        query = urlencode({"address": address, "key": self._api_key})
        data = _get_json(f"{self._geocoding_url}?{query}", timeout=self._timeout, user_agent=self._user_agent)
        status = data.get("status") if isinstance(data, dict) else None
        if status not in (None, "OK"):
            raise RoutingProviderError("routing_provider_error", f"Google Geocoding returned {status}.")
        results = data.get("results") or []
        if not results:
            return None
        location = (results[0].get("geometry") or {}).get("location") or {}
        if "lat" not in location or "lng" not in location:
            return None
        return GeoCoordinate.from_values(location["lat"], location["lng"])

    def route_distance(self, origin: GeoCoordinate, destination: GeoCoordinate) -> RouteDistance:
        query = urlencode(
            {
                "origin": origin.as_text(),
                "destination": destination.as_text(),
                "mode": "driving",
                "key": self._api_key,
            }
        )
        data = _get_json(f"{self._directions_url}?{query}", timeout=self._timeout, user_agent=self._user_agent)
        status = data.get("status") if isinstance(data, dict) else None
        if status == "ZERO_RESULTS":
            raise RoutingProviderError("no_route_found", "No road route connects those two locations.")
        if status != "OK":
            raise RoutingProviderError("routing_provider_error", f"Google Directions returned {status}.")
        routes = data.get("routes") or []
        if not routes:
            raise RoutingProviderError("no_route_found", "No road route connects those two locations.")
        legs = routes[0].get("legs") or []
        metres = 0
        for leg in legs:
            distance = leg.get("distance") or {}
            if "value" not in distance:
                raise RoutingProviderError(
                    "routing_provider_invalid_response", "Google Directions did not return a route distance."
                )
            metres += int(distance["value"])
        return RouteDistance(
            distance_km=metres_to_kilometres(metres),
            source=self.source,
            provider=self.name,
            reference=routes[0].get("summary") or None,
        )


class OsrmRoutingProvider:
    """OpenStreetMap OSRM road service + Nominatim geocoder implementation."""

    name = "OSRM"
    source = OSRM_DISTANCE_SOURCE

    def __init__(
        self,
        *,
        base_url: str | None = None,
        geocoder_url: str = NOMINATIM_SEARCH_URL,
        timeout: float | None = None,
        user_agent: str | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.routing_base_url or "https://router.project-osrm.org").rstrip("/")
        self._geocoder_url = geocoder_url
        self._timeout = timeout if timeout is not None else settings.routing_timeout_seconds
        self._user_agent = user_agent or settings.routing_user_agent

    def geocode(self, address: str) -> GeoCoordinate | None:
        query = urlencode({"q": address, "format": "json", "limit": "1"})
        data = _get_json(f"{self._geocoder_url}?{query}", timeout=self._timeout, user_agent=self._user_agent)
        if not isinstance(data, list) or not data:
            return None
        match = data[0]
        if "lat" not in match or "lon" not in match:
            return None
        return GeoCoordinate.from_values(match["lat"], match["lon"])

    def route_distance(self, origin: GeoCoordinate, destination: GeoCoordinate) -> RouteDistance:
        # OSRM takes longitude first, then latitude.
        coordinates = f"{origin.longitude},{origin.latitude};{destination.longitude},{destination.latitude}"
        url = (
            f"{self._base_url}{OSRM_ROUTE_PATH}/{quote(coordinates, safe=',;')}"
            f"?{urlencode({'overview': 'false', 'alternatives': 'false', 'steps': 'false'})}"
        )
        data = _get_json(url, timeout=self._timeout, user_agent=self._user_agent)
        code = data.get("code") if isinstance(data, dict) else None
        if code == "NoRoute":
            raise RoutingProviderError("no_route_found", "No road route connects those two locations.")
        if code != "Ok":
            raise RoutingProviderError(
                "routing_provider_error", f"OSRM returned {code or 'an unreadable response'}."
            )
        routes = data.get("routes") or []
        if not routes or "distance" not in routes[0]:
            raise RoutingProviderError("no_route_found", "No road route connects those two locations.")
        legs = routes[0].get("legs") or []
        summary = legs[0].get("summary") if legs else None
        return RouteDistance(
            distance_km=metres_to_kilometres(routes[0]["distance"]),
            source=self.source,
            provider=self.name,
            reference=summary or None,
        )


def _build_provider(name: str) -> RoutingProvider:
    settings = get_settings()
    if name == "GOOGLE_MAPS":
        if not settings.google_maps_api_key:
            raise RoutingProviderError(
                "routing_provider_unconfigured", "Google Maps routing is not configured for this deployment."
            )
        return GoogleMapsRoutingProvider(settings.google_maps_api_key.get_secret_value())
    if name == "OSRM":
        return OsrmRoutingProvider()
    raise RoutingProviderError("routing_provider_unavailable", f"Routing provider {name} is not available.")


class RoutingProviderRegistry:
    """Resolves the routing provider used for every road-route lookup.

    ``activate`` pins one provider (used by the test suite and by deployments
    that inject their own adapter); otherwise the provider named by
    ``ROUTING_PROVIDER`` is constructed lazily and cached.
    """

    def __init__(self) -> None:
        self._providers: dict[str, RoutingProvider] = {}
        self._active: RoutingProvider | None = None

    def register(self, name: str, provider: RoutingProvider) -> None:
        self._providers[name.upper()] = provider

    def activate(self, provider: RoutingProvider) -> None:
        self._active = provider

    def reset(self) -> None:
        self._active = None
        self._providers.clear()

    def get(self, name: str | None = None) -> RoutingProvider:
        if self._active is not None:
            return self._active
        provider_name = (name or get_settings().routing_provider).upper()
        provider = self._providers.get(provider_name)
        if provider is None:
            provider = _build_provider(provider_name)
            self._providers[provider_name] = provider
        return provider


routing_providers = RoutingProviderRegistry()


def get_routing_provider() -> RoutingProvider:
    """Return the routing provider configured for this deployment."""

    return routing_providers.get()

