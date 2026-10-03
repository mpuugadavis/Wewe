"""Assign a routable pickup point to existing retailers missing one.

Revision ID: 0022
Revises: 0021_hostel_coordinate_backfill
"""

from alembic import op
import sqlalchemy as sa


revision = "0022_retailer_pickup_location_backfill"
down_revision = "0021_hostel_coordinate_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing development retailers created before pickup locations became
    # required may have location_id=NULL. Use WEWE's known Kikoni shopfront
    # as their explicit development pickup point so checkout can route.
    op.execute(
        sa.text(
            """
            UPDATE retailers AS r
            SET location_id = dp.id
            FROM delivery_points AS dp
            WHERE r.location_id IS NULL
              AND dp.name = 'Kikoni shopfront'
              AND dp.owner_user_id IS NULL
              AND dp.is_active = TRUE
            """
        )
    )


def downgrade() -> None:
    # Do not erase a retailer's location during downgrade; it may have been
    # deliberately configured after this migration.
    pass
