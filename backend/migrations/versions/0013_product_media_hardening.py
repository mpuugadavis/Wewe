"""Harden product-media catalog invariants.

Revision ID: 0013
Revises: 0012
"""

from alembic import op


revision = "0013_product_media_hardening"
down_revision = "0012_notification_outbox_dispatch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Product media is currently URL-only. These constraints protect the
    # catalog even if a future write path bypasses Pydantic validation.
    op.execute(
        """
        ALTER TABLE product_images
        ADD CONSTRAINT ck_product_images_https_url
        CHECK (url LIKE 'https://%') NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE product_images
        ADD CONSTRAINT ck_product_images_sort_order_nonnegative
        CHECK (sort_order >= 0) NOT VALID
        """
    )
    op.create_index(
        "uq_product_image_product_url",
        "product_images",
        ["product_id", "url"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_product_image_product_url", table_name="product_images")
    op.execute(
        "ALTER TABLE product_images DROP CONSTRAINT ck_product_images_sort_order_nonnegative"
    )
    op.execute(
        "ALTER TABLE product_images DROP CONSTRAINT ck_product_images_https_url"
    )
