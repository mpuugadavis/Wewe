"""Add optional Google Place IDs to delivery points.

Google Routes API prefers Place IDs for property access-point accuracy. They
remain nullable because exact browser geolocation is represented by coordinates
and existing locations can continue to route by coordinates/geocoding.

Revision ID: 0009_google_place_ids
Revises: 0008_delivery_point_coordinates
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

revision = "0009_google_place_ids"
down_revision = "0008_delivery_point_coordinates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("delivery_points", sa.Column("google_place_id", sa.String(length=300), nullable=True))
    op.create_index("ix_delivery_points_google_place_id", "delivery_points", ["google_place_id"])


def downgrade() -> None:
    op.drop_index("ix_delivery_points_google_place_id", table_name="delivery_points")
    op.drop_column("delivery_points", "google_place_id")
