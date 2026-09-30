import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-for-any-deployment-000000")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "test-webhook-secret-key-not-for-deployment")
os.environ.setdefault("PAYMENT_MODE", "DISABLED")

from collections.abc import Generator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base
from app.services.routing import (
    GeoCoordinate,
    RouteDistance,
    RoutingProviderError,
    routing_providers,
)

#: Distance source recorded on quotes produced by the test routing provider.
TEST_ROAD_ROUTE = "TEST_ROAD_ROUTE"


class FakeRoutingProvider:
    """Deterministic routing-service double used by every test.

    It never touches the network and never computes a straight-line distance:
    it returns a distance that a test explicitly configured (or its default).
    Routes are keyed by origin and destination coordinates, so a test can price
    each retailer leg differently while the destination stays fixed.
    """

    name = "TEST_ROUTING"
    source = TEST_ROAD_ROUTE

    def __init__(self) -> None:
        self.default_km = Decimal("4.000")
        self.routes: dict[tuple[str, str], Decimal] = {}
        self.geocodes: dict[str, GeoCoordinate] = {}
        self.fallback_coordinate = GeoCoordinate(Decimal("0.327400"), Decimal("32.579500"))
        self.geocode_returns_none = False
        self.route_error: RoutingProviderError | None = None
        self.route_calls: list[tuple[GeoCoordinate, GeoCoordinate]] = []
        self.geocode_calls: list[str] = []

    @staticmethod
    def _key(origin: GeoCoordinate, destination: GeoCoordinate) -> tuple[str, str]:
        return origin.as_text(), destination.as_text()

    def set_route(self, origin: GeoCoordinate, destination: GeoCoordinate, distance_km) -> None:
        self.routes[self._key(origin, destination)] = Decimal(str(distance_km))

    def geocode(self, address: str) -> GeoCoordinate | None:
        self.geocode_calls.append(address)
        if self.geocode_returns_none:
            return None
        return self.geocodes.get(address, self.fallback_coordinate)

    def route_distance(self, origin: GeoCoordinate, destination: GeoCoordinate) -> RouteDistance:
        self.route_calls.append((origin, destination))
        if self.route_error is not None:
            raise self.route_error
        distance = self.routes.get(self._key(origin, destination), self.default_km)
        return RouteDistance(
            distance_km=Decimal(str(distance)).quantize(Decimal("0.001")),
            source=self.source,
            provider=self.name,
            reference="test-route",
        )


@pytest.fixture(autouse=True)
def fake_routing() -> Generator[FakeRoutingProvider, None, None]:
    """Keep every test hermetic: no test may reach a real routing service."""

    provider = FakeRoutingProvider()
    routing_providers.activate(provider)
    try:
        yield provider
    finally:
        routing_providers.reset()


@pytest.fixture
def database() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(database: Session) -> Generator[TestClient, None, None]:
    def override_get_db():
        yield database

    app.dependency_overrides[get_db] = override_get_db
    from app.limiter import limiter
    limiter.reset()

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
