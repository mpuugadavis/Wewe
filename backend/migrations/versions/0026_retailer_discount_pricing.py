"""Add retailer compare-at pricing for storefront discounts.

Revision ID: 0026_retailer_discount_pricing
Revises: 0025_profile_images_and_catalog_media
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_retailer_discount_pricing"
down_revision = "0025_profile_images_and_catalog_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("retailer_products", sa.Column("original_price_ugx", sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        "ck_retailer_products_original_price_gt_current",
        "retailer_products",
        "original_price_ugx IS NULL OR original_price_ugx > price_ugx",
    )


def downgrade() -> None:
    op.drop_constraint("ck_retailer_products_original_price_gt_current", "retailer_products", type_="check")
    op.drop_column("retailer_products", "original_price_ugx")
