"""Enforce one active delivery per rider."""
from alembic import op
import sqlalchemy as sa
revision = "0028_one_active_rider_delivery"
down_revision = "0027_delivery_offer_timestamps"
branch_labels = None
depends_on = None


def upgrade():
    # Do not silently reassign historical deliveries if conflicting data exists.
    predicate = sa.text("agent_id IS NOT NULL AND status IN ('ACCEPTED','PICKED_UP','OUT_FOR_DELIVERY')")
    op.create_index("uq_rider_active_delivery", "delivery_assignments", ["agent_id"], unique=True, postgresql_where=predicate, sqlite_where=predicate)


def downgrade():
    op.drop_index("uq_rider_active_delivery", table_name="delivery_assignments")
