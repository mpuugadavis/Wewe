"""Seed Makerere hall and nearby hostel delivery points.

Revision ID: 0010_makerere_delivery_points
Revises: 0009_google_place_ids
Create Date: 2026-09-30
"""
from uuid import uuid4
from alembic import op
from sqlalchemy import text

revision = "0010_makerere_delivery_points"
down_revision = "0009_google_place_ids"
branch_labels = None
depends_on = None

HALLS = (
    "Africa Hall", "Complex Hall", "Livingstone Hall", "Lumumba Hall",
    "Mary Stuart Hall", "Mitchell Hall", "Nkrumah Hall", "Nsibirwa Hall", "University Hall",
)
HOSTELS = ("Makerere International Students Hostel", "Muhika Hostel", "JJ Hostel")


def upgrade() -> None:
    bind = op.get_bind()
    campus = bind.execute(text("SELECT id FROM campuses WHERE slug = 'main-campus' LIMIT 1")).first()
    if not campus:
        return
    campus_id = campus[0]
    for name in HALLS:
        hall = bind.execute(text("SELECT id FROM halls WHERE campus_id = :campus_id AND name = :name LIMIT 1"), {"campus_id": campus_id, "name": name}).first()
        if not hall:
            continue
        exists = bind.execute(text("SELECT id FROM delivery_points WHERE campus_id = :campus_id AND name = :name AND owner_user_id IS NULL LIMIT 1"), {"campus_id": campus_id, "name": name}).first()
        if not exists:
            bind.execute(text("""
                INSERT INTO delivery_points (id, campus_id, hall_id, kind, name, directions, is_private, is_active, created_at, updated_at)
                VALUES (:id, :campus_id, :hall_id, 'BUILDING', :name, 'Makerere University Main Campus', false, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """), {"id": str(uuid4()), "campus_id": campus_id, "hall_id": hall[0], "name": name})
    for name in HOSTELS:
        exists = bind.execute(text("SELECT id FROM delivery_points WHERE campus_id = :campus_id AND name = :name AND owner_user_id IS NULL LIMIT 1"), {"campus_id": campus_id, "name": name}).first()
        if not exists:
            bind.execute(text("""
                INSERT INTO delivery_points (id, campus_id, kind, name, directions, is_private, is_active, created_at, updated_at)
                VALUES (:id, :campus_id, 'BUILDING', :name, 'Near Makerere University Main Campus', false, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """), {"id": str(uuid4()), "campus_id": campus_id, "name": name})


def downgrade() -> None:
    bind = op.get_bind()
    for name in HALLS + HOSTELS:
        bind.execute(text("DELETE FROM delivery_points WHERE name = :name AND owner_user_id IS NULL"), {"name": name})
