"""Regression coverage for order delivery-fee component migration."""
import runpy
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_order_delivery_fee_columns_migration_preserves_existing_order_totals():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0023_order_delivery_discount_columns.py"
    migration = runpy.run_path(str(path))
    assert migration["down_revision"] == "0022_retailer_pickup_location_backfill"
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, subtotal_ugx BIGINT NOT NULL, "
            "delivery_fee_ugx BIGINT NOT NULL, total_ugx BIGINT NOT NULL, "
            "CONSTRAINT ck_order_amounts CHECK "
            "(subtotal_ugx >= 0 AND delivery_fee_ugx >= 0 AND total_ugx >= 0))"
        ))
        connection.execute(text(
            "INSERT INTO orders (id, subtotal_ugx, delivery_fee_ugx, total_ugx) "
            "VALUES (1, 10000, 2500, 12500), (2, 2000, 0, 2000)"
        ))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
        columns = {c["name"] for c in inspect(connection).get_columns("orders")}
        assert {"gross_delivery_fee_ugx", "multi_retailer_discount_ugx", "multi_retailer_discount_percent"} <= columns
        rows = connection.execute(text(
            "SELECT subtotal_ugx, delivery_fee_ugx, total_ugx, gross_delivery_fee_ugx, "
            "multi_retailer_discount_ugx FROM orders ORDER BY id"
        )).all()
        assert [(r.total_ugx, r.gross_delivery_fee_ugx, r.multi_retailer_discount_ugx) for r in rows] == [
            (12500, 2500, 0), (2000, 0, 0)
        ]
        assert all(r.subtotal_ugx + r.delivery_fee_ugx == r.total_ugx for r in rows)
        with Operations.context(MigrationContext.configure(connection)):
            migration["downgrade"]()
        columns = {c["name"] for c in inspect(connection).get_columns("orders")}
        assert not {"gross_delivery_fee_ugx", "multi_retailer_discount_ugx", "multi_retailer_discount_percent"} & columns
        assert connection.execute(text("SELECT count(*) FROM orders")).scalar_one() == 2
    engine.dispose()
