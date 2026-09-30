"""Enforce order, monetary, and pickup-point integrity.

Revision ID: 0005_final_database_hardening
Revises: 0004_database_integrity_constraints
Create Date: 2026-09-27
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_final_database_hardening"
down_revision = "0004_database_integrity_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "pickup_points",
        "operating_status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_pickup_point_operating_status",
        "pickup_points",
        "operating_status IN ('OPEN','CLOSED','TEMPORARILY_UNAVAILABLE')",
    )
    op.create_check_constraint(
        "ck_order_destination_matches_method",
        "orders",
        "(delivery_method = 'DELIVERY' AND delivery_point_id IS NOT NULL AND pickup_point_id IS NULL) OR "
        "(delivery_method = 'PICKUP' AND delivery_point_id IS NULL AND pickup_point_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_order_total_matches_components",
        "orders",
        "total_ugx = subtotal_ugx + delivery_fee_ugx",
    )
    op.create_check_constraint(
        "ck_order_item_total_matches_price",
        "order_items",
        "line_total_ugx = unit_price_ugx * quantity",
    )


def downgrade() -> None:
    op.drop_constraint("ck_order_item_total_matches_price", "order_items", type_="check")
    op.drop_constraint("ck_order_total_matches_components", "orders", type_="check")
    op.drop_constraint("ck_order_destination_matches_method", "orders", type_="check")
    op.drop_constraint("ck_pickup_point_operating_status", "pickup_points", type_="check")
    op.alter_column(
        "pickup_points",
        "operating_status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
