"""Add order-level multi-retailer delivery discount snapshots.

Revision ID: 0023
Revises: 0022
"""

from alembic import op
import sqlalchemy as sa


revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("gross_delivery_fee_ugx", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "orders",
        sa.Column("multi_retailer_discount_ugx", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "orders",
        sa.Column(
            "multi_retailer_discount_percent",
            sa.Numeric(7, 3),
            nullable=False,
            server_default="0",
        ),
    )

    # Existing orders were priced as the full delivery fee, so preserve their
    # historical arithmetic as gross fee with no discount.
    op.execute(
        sa.text(
            "UPDATE orders "
            "SET gross_delivery_fee_ugx = delivery_fee_ugx, "
            "multi_retailer_discount_ugx = 0, "
            "multi_retailer_discount_percent = 0"
        )
    )

    op.create_check_constraint(
        "ck_order_delivery_discount_matches_components",
        "orders",
        "multi_retailer_discount_ugx <= gross_delivery_fee_ugx "
        "AND delivery_fee_ugx = gross_delivery_fee_ugx - multi_retailer_discount_ugx",
    )

    op.alter_column("orders", "gross_delivery_fee_ugx", server_default=None)
    op.alter_column("orders", "multi_retailer_discount_ugx", server_default=None)
    op.alter_column("orders", "multi_retailer_discount_percent", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "ck_order_delivery_discount_matches_components",
        "orders",
        type_="check",
    )
    op.drop_column("orders", "multi_retailer_discount_percent")
    op.drop_column("orders", "multi_retailer_discount_ugx")
    op.drop_column("orders", "gross_delivery_fee_ugx")
