"""Add controlled rider payout batches and fix payout reference cardinality.

Revision ID: 0024_rider_payout_batches
Revises: 0023_order_delivery_discount_columns, 0006_platform_commission_economics
"""

from alembic import op
import sqlalchemy as sa


revision = "0024_rider_payout_batches"
down_revision = ("0023_order_delivery_discount_columns", "0006_platform_commission_economics")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One payout reference represents one external payout/batch and therefore
    # may legitimately be shared by many delivery earnings.
    op.drop_constraint("uq_delivery_earnings_payout_reference", "delivery_earnings", type_="unique")

    op.create_table(
        "delivery_payout_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("delivery_agents.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_ugx", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="UGX"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("batch_reference", sa.String(length=180), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("payout_reference", sa.String(length=180), nullable=True),
        sa.Column(
            "authorized_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('DRAFT','SUBMITTED','SETTLED','FAILED','REVIEW_REQUIRED')",
            name="ck_delivery_payout_batch_status",
        ),
        sa.CheckConstraint("amount_ugx > 0", name="ck_delivery_payout_batch_amount"),
        sa.CheckConstraint("currency = 'UGX'", name="ck_delivery_payout_batch_currency"),
        sa.UniqueConstraint("batch_reference", name="uq_delivery_payout_batch_reference"),
        sa.UniqueConstraint("idempotency_key", name="uq_delivery_payout_batch_idempotency"),
        sa.UniqueConstraint("payout_reference", name="uq_delivery_payout_batch_payout_reference"),
    )
    op.create_index(
        "ix_delivery_payout_batches_agent_id",
        "delivery_payout_batches",
        ["agent_id"],
    )
    op.create_index(
        "ix_delivery_payout_batches_status",
        "delivery_payout_batches",
        ["status"],
    )

    op.create_table(
        "delivery_payout_batch_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Uuid(),
            sa.ForeignKey("delivery_payout_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assignment_id",
            sa.Uuid(),
            sa.ForeignKey("delivery_earnings.assignment_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_ugx", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="UGX"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "amount_ugx > 0",
            name="ck_delivery_payout_batch_line_amount",
        ),
        sa.CheckConstraint(
            "currency = 'UGX'",
            name="ck_delivery_payout_batch_line_currency",
        ),
        sa.UniqueConstraint(
            "batch_id",
            "assignment_id",
            name="uq_delivery_payout_batch_line_assignment",
        ),
    )
    op.create_index(
        "ix_delivery_payout_batch_lines_batch_id",
        "delivery_payout_batch_lines",
        ["batch_id"],
    )
    op.create_index(
        "ix_delivery_payout_batch_lines_assignment_id",
        "delivery_payout_batch_lines",
        ["assignment_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_delivery_payout_batch_lines_assignment_id",
        table_name="delivery_payout_batch_lines",
    )
    op.drop_index(
        "ix_delivery_payout_batch_lines_batch_id",
        table_name="delivery_payout_batch_lines",
    )
    op.drop_table("delivery_payout_batch_lines")
    op.drop_index(
        "ix_delivery_payout_batches_status",
        table_name="delivery_payout_batches",
    )
    op.drop_index(
        "ix_delivery_payout_batches_agent_id",
        table_name="delivery_payout_batches",
    )
    op.drop_table("delivery_payout_batches")
    op.create_unique_constraint(
        "uq_delivery_earnings_payout_reference",
        "delivery_earnings",
        ["payout_reference"],
    )
