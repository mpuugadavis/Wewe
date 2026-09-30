"""Migration coverage for the Phase 4B.3 delivery quote snapshot table."""

import runpy
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def _stub_parent_tables(connection) -> None:
    connection.execute(text("CREATE TABLE retailers (id CHAR(32) PRIMARY KEY)"))
    connection.execute(
        text(
            "CREATE TABLE retailer_fulfillments ("
            "id CHAR(32) PRIMARY KEY, retailer_id CHAR(32) NOT NULL)"
        )
    )


def _insert_quote(connection, **overrides) -> None:
    values = {
        "id": "quote-1",
        "fulfillment_id": "fulfillment-legacy",
        "retailer_id": "retailer-legacy",
        "mode": "DELIVERY",
        "route_distance_km": 5,
        "distance_source": "SUPPLIED_ROAD_ROUTE",
        "base_fee_ugx": 1500,
        "price_per_km_ugx": 500,
        "minimum_fee_ugx": 2500,
        "rounding_increment_ugx": 500,
        "rounding_tie_break": "UP",
        "pricing_version": "phase4a-com-fee-001",
        "currency": "UGX",
        "delivery_fee_ugx": 4000,
        "quoted_at": "2026-09-29 12:00:00",
    }
    values.update(overrides)
    connection.execute(
        text(
            "INSERT INTO delivery_quotes "
            "(id, fulfillment_id, retailer_id, mode, route_distance_km, distance_source, "
            "base_fee_ugx, price_per_km_ugx, minimum_fee_ugx, rounding_increment_ugx, "
            "rounding_tie_break, pricing_version, currency, delivery_fee_ugx, quoted_at) VALUES "
            "(:id, :fulfillment_id, :retailer_id, :mode, :route_distance_km, :distance_source, "
            ":base_fee_ugx, :price_per_km_ugx, :minimum_fee_ugx, :rounding_increment_ugx, "
            ":rounding_tie_break, :pricing_version, :currency, :delivery_fee_ugx, :quoted_at)"
        ),
        values,
    )


def test_delivery_quote_migration_adds_snapshot_table_and_is_reversible() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0007_delivery_quote_snapshots.py"
    )
    namespace = runpy.run_path(str(migration_path))
    assert namespace["down_revision"] == "0006_payment_attempt_uncertainty"

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _stub_parent_tables(connection)
        connection.execute(text("INSERT INTO retailers (id) VALUES ('retailer-legacy')"))
        connection.execute(
            text(
                "INSERT INTO retailer_fulfillments (id, retailer_id) "
                "VALUES ('fulfillment-legacy', 'retailer-legacy')"
            )
        )
        with Operations.context(MigrationContext.configure(connection)):
            namespace["upgrade"]()

        tables = set(inspect(connection).get_table_names())
        assert "delivery_quotes" in tables
        # Existing data is preserved by the upgrade.
        assert (
            connection.execute(text("SELECT count(*) FROM retailer_fulfillments")).scalar_one() == 1
        )

        _insert_quote(connection)
        row = connection.execute(
            text(
                "SELECT delivery_fee_ugx, route_distance_km, pricing_version "
                "FROM delivery_quotes WHERE id = 'quote-1'"
            )
        ).one()
        assert row.delivery_fee_ugx == 4000
        assert str(row.route_distance_km).startswith("5")
        assert row.pricing_version == "phase4a-com-fee-001"

        connection.execute(text("INSERT INTO retailer_fulfillments VALUES ('fulfillment-2', 'retailer-legacy')"))

        invalid_rows = (
            # Pickup pricing carries no route distance, and delivery pricing requires one.
            {"id": "quote-2", "fulfillment_id": "fulfillment-2", "mode": "PICKUP", "route_distance_km": 3},
            {"id": "quote-2", "fulfillment_id": "fulfillment-2", "mode": "DELIVERY", "route_distance_km": None},
            {"id": "quote-2", "fulfillment_id": "fulfillment-2", "route_distance_km": -1},
            {"id": "quote-2", "fulfillment_id": "fulfillment-2", "delivery_fee_ugx": -1},
            {"id": "quote-2", "fulfillment_id": "fulfillment-2", "mode": "WHATEVER"},
            {"id": "quote-2", "fulfillment_id": "fulfillment-2", "currency": "USD"},
            # One committed quote per fulfillment.
            {"id": "quote-2", "fulfillment_id": "fulfillment-legacy"},
        )
        for invalid in invalid_rows:
            with pytest.raises(IntegrityError):
                _insert_quote(connection, **invalid)

        with Operations.context(MigrationContext.configure(connection)):
            namespace["downgrade"]()

        assert "delivery_quotes" not in set(inspect(connection).get_table_names())
        assert (
            connection.execute(text("SELECT count(*) FROM retailer_fulfillments")).scalar_one() == 2
        )
    engine.dispose()
