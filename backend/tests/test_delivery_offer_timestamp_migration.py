import runpy
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_offer_timestamp_upgrade_preserves_existing_offers():
    migration = runpy.run_path(str(Path(__file__).parents[1] / "migrations/versions/0027_delivery_offer_timestamps.py"))
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE delivery_offers (id INTEGER PRIMARY KEY, offered_at DATETIME NOT NULL, responded_at DATETIME)"))
        connection.execute(text("INSERT INTO delivery_offers VALUES (1, '2026-10-01 10:00:00', NULL), (2, '2026-10-01 10:00:00', '2026-10-01 10:05:00')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
        columns = {c["name"]: c for c in inspect(connection).get_columns("delivery_offers")}
        assert not columns["created_at"]["nullable"]
        assert not columns["updated_at"]["nullable"]
        rows = connection.execute(text("SELECT created_at, updated_at FROM delivery_offers ORDER BY id")).all()
        assert rows == [("2026-10-01 10:00:00", "2026-10-01 10:00:00"), ("2026-10-01 10:00:00", "2026-10-01 10:05:00")]
        connection.execute(text("INSERT INTO delivery_offers (id, offered_at) VALUES (3, CURRENT_TIMESTAMP)"))
        assert connection.execute(text("SELECT created_at IS NOT NULL AND updated_at IS NOT NULL FROM delivery_offers WHERE id=3")).scalar_one()
        with Operations.context(MigrationContext.configure(connection)):
            migration["downgrade"]()
        assert connection.execute(text("SELECT count(*) FROM delivery_offers")).scalar_one() == 3
