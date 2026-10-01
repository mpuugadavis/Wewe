"""Add uploaded product-media metadata.

Revision ID: 0014
Revises: 0013_product_media_hardening
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_product_media_upload_metadata"
down_revision = "0013_product_media_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("product_images", sa.Column("storage_key", sa.String(length=500), nullable=True))
    op.add_column("product_images", sa.Column("content_type", sa.String(length=50), nullable=True))
    op.add_column("product_images", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("product_images", sa.Column("width", sa.Integer(), nullable=True))
    op.add_column("product_images", sa.Column("height", sa.Integer(), nullable=True))
    op.create_unique_constraint("uq_product_images_storage_key", "product_images", ["storage_key"])
    op.create_check_constraint(
        "ck_product_images_metadata_pair",
        "product_images",
        "(storage_key IS NULL AND content_type IS NULL AND size_bytes IS NULL AND width IS NULL AND height IS NULL) "
        "OR (storage_key IS NOT NULL AND content_type IN ('image/jpeg','image/png','image/webp') "
        "AND size_bytes > 0 AND width > 0 AND height > 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_product_images_metadata_pair", "product_images", type_="check")
    op.drop_constraint("uq_product_images_storage_key", "product_images", type_="unique")
    op.drop_column("product_images", "height")
    op.drop_column("product_images", "width")
    op.drop_column("product_images", "size_bytes")
    op.drop_column("product_images", "content_type")
    op.drop_column("product_images", "storage_key")
