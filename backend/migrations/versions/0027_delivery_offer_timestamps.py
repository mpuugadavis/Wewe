"""Repair delivery offer timestamps omitted from the original table migration."""
from alembic import op
import sqlalchemy as sa

revision = "0027_delivery_offer_timestamps"
down_revision = "0026_retailer_discount_pricing"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("delivery_offers") as batch:
        for name in ("created_at", "updated_at"):
            batch.add_column(sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.execute(sa.text("UPDATE delivery_offers SET created_at = offered_at, updated_at = COALESCE(responded_at, offered_at)"))


def downgrade():
    op.drop_column("delivery_offers", "updated_at")
    op.drop_column("delivery_offers", "created_at")
