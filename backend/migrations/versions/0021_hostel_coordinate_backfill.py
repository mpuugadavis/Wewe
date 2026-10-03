"""Backfill coordinates for Makerere hostel delivery points.

Revision ID: 0021
Revises: 0020_delivery_point_coordinate_backfill
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_hostel_coordinate_backfill"
down_revision = "0020_delivery_point_coordinate_backfill"
branch_labels = None
depends_on = None


HOSTEL_COORDINATES = {
    "Makerere International Students Hostel": ("0.334990", "32.560500"),
    "Muhika Hostel": ("0.333190", "32.562550"),
    "JJ Hostel": ("0.333050", "32.562700"),
}


def upgrade() -> None:
    table = sa.table(
        "delivery_points",
        sa.column("name", sa.String()),
        sa.column("owner_user_id", sa.Uuid()),
        sa.column("latitude", sa.Numeric()),
        sa.column("longitude", sa.Numeric()),
    )
    for name, (latitude, longitude) in HOSTEL_COORDINATES.items():
        op.execute(
            table.update()
            .where(
                sa.and_(
                    table.c.name == name,
                    table.c.owner_user_id.is_(None),
                    sa.or_(table.c.latitude.is_(None), table.c.longitude.is_(None)),
                )
            )
            .values(latitude=latitude, longitude=longitude)
        )


def downgrade() -> None:
    table = sa.table(
        "delivery_points",
        sa.column("name", sa.String()),
        sa.column("owner_user_id", sa.Uuid()),
        sa.column("latitude", sa.Numeric()),
        sa.column("longitude", sa.Numeric()),
    )
    for name, (latitude, longitude) in HOSTEL_COORDINATES.items():
        op.execute(
            table.update()
            .where(
                sa.and_(
                    table.c.name == name,
                    table.c.owner_user_id.is_(None),
                    table.c.latitude == sa.cast(latitude, sa.Numeric()),
                    table.c.longitude == sa.cast(longitude, sa.Numeric()),
                )
            )
            .values(latitude=None, longitude=None)
        )
