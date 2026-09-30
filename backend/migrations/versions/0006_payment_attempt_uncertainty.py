"""Add payment attempt identity, uncertainty, reconciliation, and refund reservations.

Revision ID: 0006_payment_attempt_uncertainty
Revises: 0005_final_database_hardening
Create Date: 2026-09-28
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_payment_attempt_uncertainty"
down_revision = "0005_final_database_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("payments") as batch_op:
        batch_op.add_column(sa.Column("attempt_reference", sa.String(length=180), nullable=True))
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=180), nullable=True))
        batch_op.add_column(sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))

    connection = op.get_bind()
    legacy_payment_ids = connection.execute(sa.text("SELECT id FROM payments")).scalars().all()
    for payment_id in legacy_payment_ids:
        connection.execute(
            sa.text("UPDATE payments SET attempt_reference = :attempt_reference WHERE id = :payment_id"),
            {
                "attempt_reference": f"legacy-{payment_id}",
                "payment_id": payment_id,
            },
        )

    with op.batch_alter_table("payments") as batch_op:
        batch_op.alter_column(
            "attempt_reference",
            existing_type=sa.String(length=180),
            nullable=False,
        )
        batch_op.drop_constraint("ck_payment_status", type_="check")
        batch_op.create_check_constraint(
            "ck_payment_status",
            "status IN ('PENDING','UNKNOWN','SUCCESSFUL','FAILED','REFUNDED')",
        )
        batch_op.create_unique_constraint("uq_payment_attempt_reference", ["attempt_reference"])
        batch_op.create_unique_constraint("uq_payment_idempotency_key", ["idempotency_key"])

    with op.batch_alter_table("payment_events") as batch_op:
        batch_op.add_column(
            sa.Column(
                "disposition",
                sa.String(length=20),
                server_default=sa.text("'APPLIED'"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_payment_event_disposition",
            "disposition IN ('APPLIED','IDEMPOTENT','CONFLICT')",
        )

    op.create_table(
        "payment_reconciliations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("payment_event_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('REQUESTED','ATTEMPTED','UNRESOLVED','AUTHORITATIVE_SUCCESS',"
            "'AUTHORITATIVE_FAILURE','CONFLICT','MANUAL_REVIEW')",
            name="ck_payment_reconciliation_state",
        ),
        sa.CheckConstraint("source IN ('SYSTEM','PROVIDER')", name="ck_payment_reconciliation_source"),
        sa.ForeignKeyConstraint(["payment_event_id"], ["payment_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payment_reconciliations_payment_id",
        "payment_reconciliations",
        ["payment_id"],
        unique=False,
    )
    op.create_index(
        "ix_payment_reconciliations_payment_event_id",
        "payment_reconciliations",
        ["payment_event_id"],
        unique=False,
    )

    op.create_table(
        "payment_refunds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("amount_ugx", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=True),
        sa.Column("external_reference", sa.String(length=180), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_ugx > 0", name="ck_payment_refund_amount"),
        sa.CheckConstraint(
            "status IN ('SUBMITTED','UNKNOWN','CONFIRMED','FAILED')",
            name="ck_payment_refund_status",
        ),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_payment_refund_idempotency_key"),
        sa.UniqueConstraint("external_reference", name="uq_payment_refund_external_reference"),
    )
    op.create_index("ix_payment_refunds_payment_id", "payment_refunds", ["payment_id"], unique=False)
    op.create_index("ix_payment_refunds_status", "payment_refunds", ["status"], unique=False)


def downgrade() -> None:
    connection = op.get_bind()
    unknown_count = connection.execute(
        sa.text("SELECT count(*) FROM payments WHERE status = 'UNKNOWN'")
    ).scalar_one()
    if unknown_count:
        raise RuntimeError("Cannot downgrade while payments have unresolved UNKNOWN status.")

    op.drop_index("ix_payment_refunds_status", table_name="payment_refunds")
    op.drop_index("ix_payment_refunds_payment_id", table_name="payment_refunds")
    op.drop_table("payment_refunds")
    op.drop_index("ix_payment_reconciliations_payment_event_id", table_name="payment_reconciliations")
    op.drop_index("ix_payment_reconciliations_payment_id", table_name="payment_reconciliations")
    op.drop_table("payment_reconciliations")

    with op.batch_alter_table("payment_events") as batch_op:
        batch_op.drop_constraint("ck_payment_event_disposition", type_="check")
        batch_op.drop_column("disposition")

    with op.batch_alter_table("payments") as batch_op:
        batch_op.drop_constraint("uq_payment_idempotency_key", type_="unique")
        batch_op.drop_constraint("uq_payment_attempt_reference", type_="unique")
        batch_op.drop_constraint("ck_payment_status", type_="check")
        batch_op.create_check_constraint(
            "ck_payment_status",
            "status IN ('PENDING','SUCCESSFUL','FAILED','REFUNDED')",
        )
        batch_op.drop_column("resolved_at")
        batch_op.drop_column("initiated_at")
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("attempt_reference")
