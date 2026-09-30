"""Add optional coordinates to delivery points.

Road-route distance calculation (COM-FEE-004) needs a real origin and
destination. Delivery points — which cover both customer drop-off points and
retailer/pickup locations — may now carry their WGS84 coordinates so the
routing service can price a route without geocoding on every checkout. The
columns are nullable: a point without coordinates is geocoded from its address
instead, and a point that cannot be located refuses the delivery rather than
inventing a distance (COM-FEE-009).

No existing column, constraint, or row is altered.

Revision ID: 0008_delivery_point_coordinates
Revises: 0007_delivery_quote_snapshots
Create Date: 2026-09-29
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_delivery_point_coordinates"
down_revision = "0007_delivery_quote_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("delivery_points", sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=True))
    op.add_column("delivery_points", sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=True))
    with op.batch_alter_table("delivery_points") as batch_op:
        batch_op.create_check_constraint(
            "ck_delivery_point_latitude_range",
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
        )
        batch_op.create_check_constraint(
            "ck_delivery_point_longitude_range",
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
        )
        batch_op.create_check_constraint(
            "ck_delivery_point_coordinate_pair",
            "(latitude IS NULL) = (longitude IS NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("delivery_points") as batch_op:
        batch_op.drop_constraint("ck_delivery_point_coordinate_pair", type_="check")
        batch_op.drop_constraint("ck_delivery_point_longitude_range", type_="check")
        batch_op.drop_constraint("ck_delivery_point_latitude_range", type_="check")
    op.drop_column("delivery_points", "longitude")
    op.drop_column("delivery_points", "latitude")
