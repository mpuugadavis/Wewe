"""Add per-fulfillment delivery quote snapshots.

Phase 4B.3 stores the committed approved Phase 4A COM-FEE delivery-pricing
calculation (fulfillment/retailer identity, delivery/pickup mode, supplied
road-route distance and its source, base fee, price per km, minimum fee,
rounding configuration, pricing version, and the resulting integer-UGX fee) so
later pricing-configuration changes cannot silently change an existing order.

No existing table can hold that snapshot, so this revision adds one new table.
It does not alter any existing table or row.

Revision ID: 0007_delivery_quote_snapshots
Revises: 0006_payment_attempt_uncertainty
Create Date: 2026-09-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_delivery_quote_snapshots"
down_revision = "0006_payment_attempt_uncertainty"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_quotes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fulfillment_id", sa.Uuid(), nullable=False),
        sa.Column("retailer_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("route_distance_km", sa.Numeric(precision=9, scale=3), nullable=True),
        sa.Column("distance_source", sa.String(length=40), nullable=True),
        sa.Column("base_fee_ugx", sa.BigInteger(), nullable=False),
        sa.Column("price_per_km_ugx", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("minimum_fee_ugx", sa.BigInteger(), nullable=False),
        sa.Column("rounding_increment_ugx", sa.BigInteger(), nullable=False),
        sa.Column("rounding_tie_break", sa.String(length=8), nullable=False),
        sa.Column("pricing_version", sa.String(length=60), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("delivery_fee_ugx", sa.BigInteger(), nullable=False),
        sa.Column("quoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("mode IN ('DELIVERY','PICKUP')", name="ck_delivery_quote_mode"),
        sa.CheckConstraint(
            "(mode = 'DELIVERY' AND route_distance_km IS NOT NULL) OR "
            "(mode = 'PICKUP' AND route_distance_km IS NULL)",
            name="ck_delivery_quote_distance_matches_mode",
        ),
        sa.CheckConstraint(
            "route_distance_km IS NULL OR route_distance_km >= 0",
            name="ck_delivery_quote_distance_nonnegative",
        ),
        sa.CheckConstraint("delivery_fee_ugx >= 0", name="ck_delivery_quote_amount"),
        sa.CheckConstraint(
            "base_fee_ugx >= 0 AND price_per_km_ugx >= 0 AND minimum_fee_ugx >= 0 "
            "AND rounding_increment_ugx > 0",
            name="ck_delivery_quote_pricing_parameters",
        ),
        sa.CheckConstraint("currency = 'UGX'", name="ck_delivery_quote_currency"),
        sa.ForeignKeyConstraint(
            ["fulfillment_id"], ["retailer_fulfillments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fulfillment_id", name="uq_delivery_quote_fulfillment"),
    )
    op.create_index(
        "ix_delivery_quotes_retailer_id",
        "delivery_quotes",
        ["retailer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_quotes_retailer_id", table_name="delivery_quotes")
    op.drop_table("delivery_quotes")
