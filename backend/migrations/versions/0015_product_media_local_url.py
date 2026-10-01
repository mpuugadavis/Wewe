"""Allow loopback HTTP product-media URLs for local development.

Revision ID: 0015
Revises: 0014_product_media_upload_metadata
"""

from alembic import op


revision = "0015_product_media_local_url"
down_revision = "0014_product_media_upload_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Production media URLs remain HTTPS-only. Local development uses the
    # browser-accessible MinIO endpoint on localhost/127.0.0.1 over HTTP.
    op.drop_constraint("ck_product_images_https_url", "product_images", type_="check")
    op.create_check_constraint(
        "ck_product_images_https_url",
        "product_images",
        "url LIKE 'https://%' "
        "OR url LIKE 'http://localhost:%' "
        "OR url LIKE 'http://127.0.0.1:%'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_product_images_https_url", "product_images", type_="check")
    op.create_check_constraint(
        "ck_product_images_https_url",
        "product_images",
        "url LIKE 'https://%'",
    )
