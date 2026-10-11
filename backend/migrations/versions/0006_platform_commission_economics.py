"""Add snapshotted marketplace commission economics to orders.

Revision ID: 0006_platform_commission_economics
Revises: 0005_final_database_hardening
Create Date: 2026-10-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_platform_commission_economics"
down_revision = "0005_final_database_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "platform_commission_percent",
            sa.Numeric(7, 3),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "platform_commission_ugx",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    # Preserve historical order economics. New orders snapshot the configured
    # commission at checkout; legacy orders remain explicitly commission-free.
    op.alter_column(
        "orders",
        "platform_commission_percent",
        server_default="8",
    )
    op.alter_column(
        "orders",
        "platform_commission_ugx",
        server_default="0",
    )
    op.create_check_constraint(
        "ck_order_platform_commission_percent",
        "orders",
        "platform_commission_percent >= 0 AND platform_commission_percent <= 30",
    )
    op.create_check_constraint(
        "ck_order_platform_commission_amount",
        "orders",
        "platform_commission_ugx >= 0 AND platform_commission_ugx <= subtotal_ugx",
    )


def downgrade() -> None:
    op.drop_constraint("ck_order_platform_commission_amount", "orders", type_="check")
    op.drop_constraint("ck_order_platform_commission_percent", "orders", type_="check")
    op.drop_column("orders", "platform_commission_ugx")
    op.drop_column("orders", "platform_commission_percent")
