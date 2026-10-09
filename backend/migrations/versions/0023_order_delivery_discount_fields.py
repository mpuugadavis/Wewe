"""Add delivery-fee components required by customer order reads.

Revision ID: 0023_order_delivery_discount_fields
Revises: 0022_retailer_pickup_location_backfill
"""

from alembic import op
import sqlalchemy as sa


revision = "0023_order_delivery_discount_fields"
down_revision = "0022_retailer_pickup_location_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep existing orders valid and preserve their current delivery fee/total.
    # Historical orders cannot reliably reconstruct a pre-discount gross fee,
    # so treat the stored fee as gross and apply no historical discount.
    op.add_column(
        "orders",
        sa.Column("gross_delivery_fee_ugx", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column(
        "orders",
        sa.Column("multi_retailer_discount_ugx", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column(
        "orders",
        sa.Column(
            "multi_retailer_discount_percent",
            sa.Numeric(7, 3),
            server_default="0",
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE orders SET gross_delivery_fee_ugx = delivery_fee_ugx, "
        "multi_retailer_discount_ugx = 0, multi_retailer_discount_percent = 0"
    )

    # Replace the initial schema's narrower amount check with the current model
    # invariant. Existing totals are not changed by this migration.
    op.drop_constraint("ck_order_amounts", "orders", type_="check")
    op.create_check_constraint(
        "ck_order_amounts",
        "orders",
        "subtotal_ugx >= 0 AND gross_delivery_fee_ugx >= 0 "
        "AND multi_retailer_discount_ugx >= 0 AND delivery_fee_ugx >= 0 "
        "AND total_ugx >= 0",
    )
    op.create_check_constraint(
        "ck_order_delivery_discount_matches_components",
        "orders",
        "multi_retailer_discount_ugx <= gross_delivery_fee_ugx "
        "AND delivery_fee_ugx = gross_delivery_fee_ugx - multi_retailer_discount_ugx",
    )
    op.create_check_constraint(
        "ck_order_total_matches_components",
        "orders",
        "total_ugx = subtotal_ugx + delivery_fee_ugx",
    )


def downgrade() -> None:
    op.drop_constraint("ck_order_total_matches_components", "orders", type_="check")
    op.drop_constraint(
        "ck_order_delivery_discount_matches_components", "orders", type_="check"
    )
    op.drop_constraint("ck_order_amounts", "orders", type_="check")
    op.create_check_constraint(
        "ck_order_amounts",
        "orders",
        "subtotal_ugx >= 0 AND delivery_fee_ugx >= 0 AND total_ugx >= 0",
    )
    op.drop_column("orders", "multi_retailer_discount_percent")
    op.drop_column("orders", "multi_retailer_discount_ugx")
    op.drop_column("orders", "gross_delivery_fee_ugx")
