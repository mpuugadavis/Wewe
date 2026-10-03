"""Backfill curated Makerere delivery-point coordinates for reliable routing.

Revision ID: 0020_delivery_point_coordinate_backfill
Revises: 0019_worker_health
"""
from alembic import op
from sqlalchemy import text

revision = "0020_delivery_point_coordinate_backfill"
down_revision = "0019_worker_health"
branch_labels = None
depends_on = None

POINTS = {
    "Africa Hall": ("0.337890", "32.568910"),
    "Complex Hall": ("0.329530", "32.569750"),
    "Livingstone Hall": ("0.338770", "32.567990"),
    "Lumumba Hall": ("0.331960", "32.566610"),
    "Mary Stuart Hall": ("0.330580", "32.566590"),
    "Mitchell Hall": ("0.332530", "32.570580"),
    "Nkrumah Hall": ("0.335840", "32.569380"),
    "Nsibirwa Hall": ("0.336080", "32.569900"),
    "University Hall": ("0.332897", "32.572208"),
    "Kikoni shopfront": ("0.335300", "32.571300"),
    "Main Library pickup desk": ("0.327000", "32.580600"),
}


def upgrade() -> None:
    bind = op.get_bind()
    for name, (latitude, longitude) in POINTS.items():
        bind.execute(
            text(
                """
                UPDATE delivery_points
                   SET latitude = :latitude,
                       longitude = :longitude,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE name = :name
                   AND owner_user_id IS NULL
                """
            ),
            {"name": name, "latitude": latitude, "longitude": longitude},
        )
    # The seeded test customer's preferred private destination is also given
    # a stable coordinate so checkout never depends on geocoding it.
    bind.execute(
        text(
            """
            UPDATE delivery_points
               SET latitude = COALESCE(latitude, :latitude),
                   longitude = COALESCE(longitude, :longitude),
                   updated_at = CURRENT_TIMESTAMP
             WHERE name = 'Room 12'
               AND is_private = true
            """
        ),
        {"latitude": "0.331700", "longitude": "32.574400"},
    )


def downgrade() -> None:
    bind = op.get_bind()
    for name in POINTS:
        bind.execute(
            text(
                """
                UPDATE delivery_points
                   SET latitude = NULL,
                       longitude = NULL,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE name = :name
                   AND owner_user_id IS NULL
                """
            ),
            {"name": name},
        )
