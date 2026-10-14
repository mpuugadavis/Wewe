import runpy
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def test_single_rider_constraint_preserves_history_and_rejects_active_duplicates():
    migration = runpy.run_path(str(Path(__file__).parents[1] / "migrations/versions/0028_one_active_rider_delivery.py"))
    with create_engine("sqlite://").begin() as connection:
        connection.execute(text("CREATE TABLE delivery_assignments (id INTEGER PRIMARY KEY, agent_id TEXT, status TEXT)"))
        connection.execute(text("INSERT INTO delivery_assignments VALUES (1,'rider','DELIVERED'),(2,'rider','ACCEPTED')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
        for status in ("ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY"):
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(text("INSERT INTO delivery_assignments VALUES (3,'rider',:status)"), {"status": status})
        connection.execute(text("UPDATE delivery_assignments SET status='DELIVERED' WHERE id=2"))
        connection.execute(text("INSERT INTO delivery_assignments VALUES (3,'rider','ACCEPTED')"))
        assert connection.execute(text("SELECT count(*) FROM delivery_assignments")).scalar_one() == 3
