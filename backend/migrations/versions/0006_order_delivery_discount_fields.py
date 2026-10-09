"""Add delivery-fee breakdown fields required by the current Order model.

Revision ID: 0006_order_delivery_discount_fields
Revises: 0005_final_database_hardening
Create Date: 2026-10-09

Older orders retain their previously charged delivery fee as the gross fee and
receive a zero discount. This preserves every existing order total.
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_order_delivery_discount_fields"
down_revision = "0005_final_database_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "gross_delivery_fee_ugx",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "multi_retailer_discount_ugx",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "multi_retailer_discount_percent",
            sa.Numeric(precision=7, scale=3),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )

    # Preserve the economics of existing orders: before the discount breakdown
    # existed, delivery_fee_ugx was the actual fee charged to the customer.
    op.execute(
        """
        UPDATE orders
        SET gross_delivery_fee_ugx = delivery_fee_ugx,
            multi_retailer_discount_ugx = 0,
            multi_retailer_discount_percent = 0
        """
    )

    op.create_check_constraint(
        "ck_order_delivery_discount_matches_components",
        "orders",
        "gross_delivery_fee_ugx >= 0 "
        "AND multi_retailer_discount_ugx >= 0 "
        "AND multi_retailer_discount_percent >= 0 "
        "AND multi_retailer_discount_ugx <= gross_delivery_fee_ugx "
        "AND delivery_fee_ugx = gross_delivery_fee_ugx - multi_retailer_discount_ugx",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_order_delivery_discount_matches_components", "orders", type_="check"
    )
    op.drop_column("orders", "multi_retailer_discount_percent")
    op.drop_column("orders", "multi_retailer_discount_ugx")
    op.drop_column("orders", "gross_delivery_fee_ugx")
