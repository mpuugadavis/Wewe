import runpy
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def test_online_payment_method_migration_rejects_cash_rows() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0011_online_payment_methods.py"
    )
    module = runpy.run_path(str(migration_path))
    engine = create_engine("sqlite://")

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE payments ("
                "id CHAR(32) PRIMARY KEY, "
                "method VARCHAR(24) NOT NULL"
                ")"
            )
        )
        connection.execute(text("INSERT INTO payments (id, method) VALUES ('payment-1', 'MTN_MOMO')"))

        with Operations.context(MigrationContext.configure(connection)):
            module["upgrade"]()

        connection.execute(text("INSERT INTO payments (id, method) VALUES ('payment-2', 'AIRTEL_MONEY')"))

        with pytest.raises(IntegrityError):
            connection.execute(text("INSERT INTO payments (id, method) VALUES ('payment-3', 'CASH')"))

        with pytest.raises(IntegrityError):
            connection.execute(
                text("UPDATE payments SET method = 'CASH' WHERE id = 'payment-1'")
            )

        with Operations.context(MigrationContext.configure(connection)):
            module["downgrade"]()

        connection.execute(text("INSERT INTO payments (id, method) VALUES ('payment-4', 'CASH')"))

    engine.dispose()
