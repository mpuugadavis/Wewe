"""Add order delivery-fee components required by current order pricing.

Revision ID: 0023_order_delivery_discount_columns
Revises: 0022_retailer_pickup_location_backfill
"""

from alembic import op
import sqlalchemy as sa


revision = "0023_order_delivery_discount_columns"
down_revision = "0022_retailer_pickup_location_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Replace the original amount check because the current model includes the
    # gross fee and discount components in that invariant.
    op.drop_constraint("ck_order_amounts", "orders", type_="check")

    op.add_column(
        "orders",
        sa.Column(
            "gross_delivery_fee_ugx",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "multi_retailer_discount_ugx",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "multi_retailer_discount_percent",
            sa.Numeric(precision=7, scale=3),
            server_default="0",
            nullable=False,
        ),
    )

    # Preserve existing order totals: historically delivery_fee_ugx stored the
    # final fee, so treat it as the gross fee and record no legacy discount.
    op.execute(
        sa.text(
            "UPDATE orders "
            "SET gross_delivery_fee_ugx = delivery_fee_ugx, "
            "multi_retailer_discount_ugx = 0, "
            "multi_retailer_discount_percent = 0"
        )
    )

    op.create_check_constraint(
        "ck_order_amounts",
        "orders",
        "subtotal_ugx >= 0 AND gross_delivery_fee_ugx >= 0 "
        "AND multi_retailer_discount_ugx >= 0 "
        "AND delivery_fee_ugx >= 0 AND total_ugx >= 0",
    )
    op.create_check_constraint(
        "ck_order_delivery_discount_matches_components",
        "orders",
        "multi_retailer_discount_ugx <= gross_delivery_fee_ugx "
        "AND delivery_fee_ugx = gross_delivery_fee_ugx - multi_retailer_discount_ugx",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_order_delivery_discount_matches_components",
        "orders",
        type_="check",
    )
    op.drop_constraint("ck_order_amounts", "orders", type_="check")

    op.drop_column("orders", "multi_retailer_discount_percent")
    op.drop_column("orders", "multi_retailer_discount_ugx")
    op.drop_column("orders", "gross_delivery_fee_ugx")

    op.create_check_constraint(
        "ck_order_amounts",
        "orders",
        "subtotal_ugx >= 0 AND delivery_fee_ugx >= 0 AND total_ugx >= 0",
    )
