"""Add profile image storage and backfill distinct demo product images.

Revision ID: 0025_profile_images_and_catalog_media
Revises: 0024_rider_payout_batches
Create Date: 2026-10-11
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision = "0025_profile_images_and_catalog_media"
down_revision = "0024_rider_payout_batches"
branch_labels = None
depends_on = None


DEMO_IMAGES = {
    "Campus Classic Hoodie": "https://images.unsplash.com/photo-1521803751845-f36d43bb1f76?auto=format&fit=crop&w=1200&q=85",
    "Chicken & Chips Combo": "https://images.unsplash.com/photo-1548340748-6d2b7d7da280?auto=format&fit=crop&w=1200&q=85",
    "Everyday Canvas Tote": "https://images.unsplash.com/photo-1780480999314-b82a1f2f9de6?auto=format&fit=crop&w=1200&q=85",
    "Study Notes Bundle": "https://images.unsplash.com/photo-1764818959104-995873e9add5?auto=format&fit=crop&w=1200&q=85",
}


def upgrade() -> None:
    op.add_column("users", sa.Column("profile_image_storage_key", sa.String(length=500), nullable=True))
    op.add_column("users", sa.Column("profile_image_content_type", sa.String(length=50), nullable=True))
    op.add_column("users", sa.Column("profile_image_size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("profile_image_width", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("profile_image_height", sa.Integer(), nullable=True))
    op.create_unique_constraint("uq_users_profile_image_storage_key", "users", ["profile_image_storage_key"])

    bind = op.get_bind()
    for product_name, image_url in DEMO_IMAGES.items():
        product_id = bind.execute(
            sa.text("SELECT id FROM products WHERE name = :name ORDER BY created_at LIMIT 1"),
            {"name": product_name},
        ).scalar_one_or_none()
        if product_id is None:
            continue
        exists = bind.execute(
            sa.text("SELECT 1 FROM product_images WHERE product_id = :product_id LIMIT 1"),
            {"product_id": product_id},
        ).scalar_one_or_none()
        if exists is not None:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO product_images
                    (id, product_id, url, alt_text, sort_order, storage_key, content_type, size_bytes, width, height, created_at, updated_at)
                VALUES
                    (:id, :product_id, :url, :alt_text, 0, NULL, NULL, NULL, NULL, NULL, NOW(), NOW())
                """
            ),
            {
                "id": uuid4(),
                "product_id": product_id,
                "url": image_url,
                "alt_text": product_name,
            },
        )


def downgrade() -> None:
    for product_name in DEMO_IMAGES:
        op.execute(
            sa.text(
                "DELETE FROM product_images "
                "WHERE product_id IN (SELECT id FROM products WHERE name = :name) "
                "AND storage_key IS NULL"
            ),
            {"name": product_name},
        )
    op.drop_constraint("uq_users_profile_image_storage_key", "users", type_="unique")
    op.drop_column("users", "profile_image_height")
    op.drop_column("users", "profile_image_width")
    op.drop_column("users", "profile_image_size_bytes")
    op.drop_column("users", "profile_image_content_type")
    op.drop_column("users", "profile_image_storage_key")
