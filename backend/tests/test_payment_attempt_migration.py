import runpy
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_payment_attempt_migration_preserves_legacy_rows_and_adds_attempt_schema() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0006_payment_attempt_uncertainty.py"
    )
    upgrade = runpy.run_path(str(migration_path))["upgrade"]
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE payments ("
                "id CHAR(32) PRIMARY KEY, order_id CHAR(32) NOT NULL, customer_id CHAR(32) NOT NULL, "
                "amount_ugx BIGINT NOT NULL, currency VARCHAR(3) NOT NULL, method VARCHAR(24) NOT NULL, "
                "provider VARCHAR(60) NOT NULL, provider_reference VARCHAR(180), status VARCHAR(20) NOT NULL, "
                "paid_at DATETIME, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, "
                "CONSTRAINT ck_payment_amount_currency CHECK (amount_ugx > 0 AND currency = 'UGX'), "
                "CONSTRAINT ck_payment_status CHECK (status IN ('PENDING','SUCCESSFUL','FAILED','REFUNDED')), "
                "CONSTRAINT uq_legacy_provider_reference UNIQUE (provider_reference))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE payment_events ("
                "id CHAR(32) PRIMARY KEY, payment_id CHAR(32) NOT NULL, "
                "provider_event_id VARCHAR(180) NOT NULL UNIQUE, status VARCHAR(20) NOT NULL, "
                "received_at DATETIME NOT NULL, "
                "CONSTRAINT ck_payment_event_status CHECK (status IN ('SUCCESSFUL','FAILED','REFUNDED')))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO payments "
                "(id, order_id, customer_id, amount_ugx, currency, method, provider, provider_reference, "
                "status, paid_at, created_at, updated_at) VALUES "
                "('payment-legacy', 'order-legacy', 'customer-legacy', 27500, 'UGX', 'MTN_MOMO', "
                "'MTN_MOMO', 'provider-legacy-reference', 'SUCCESSFUL', "
                "'2026-09-27 12:00:00', '2026-09-27 11:00:00', '2026-09-27 12:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO payment_events "
                "(id, payment_id, provider_event_id, status, received_at) VALUES "
                "('event-legacy', 'payment-legacy', 'MTN_MOMO:legacy-event', 'SUCCESSFUL', "
                "'2026-09-27 12:00:00')"
            )
        )
        with Operations.context(MigrationContext.configure(connection)):
            upgrade()

        legacy_payment = connection.execute(
            text(
                "SELECT status, amount_ugx, currency, provider_reference, attempt_reference, "
                "idempotency_key, initiated_at, resolved_at FROM payments WHERE id = 'payment-legacy'"
            )
        ).one()
        legacy_event = connection.execute(
            text(
                "SELECT status, disposition FROM payment_events WHERE id = 'event-legacy'"
            )
        ).one()

        assert legacy_payment.status == "SUCCESSFUL"
        assert legacy_payment.amount_ugx == 27500
        assert legacy_payment.currency == "UGX"
        assert legacy_payment.provider_reference == "provider-legacy-reference"
        assert legacy_payment.attempt_reference == "legacy-payment-legacy"
        assert legacy_payment.idempotency_key is None
        assert legacy_payment.initiated_at is None
        assert legacy_payment.resolved_at is None
        assert legacy_event.status == "SUCCESSFUL"
        assert legacy_event.disposition == "APPLIED"
        assert {
            "payment_refunds",
            "payment_reconciliations",
        }.issubset(set(inspect(connection).get_table_names()))
        connection.execute(text("UPDATE payments SET status = 'UNKNOWN' WHERE id = 'payment-legacy'"))
    engine.dispose()
