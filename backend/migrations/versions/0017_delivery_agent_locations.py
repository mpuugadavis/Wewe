"""Add delivery agent live location storage.

Revision ID: 0017
Revises: 0016_retailer_settlement_ledger
"""

from alembic import op
import sqlalchemy as sa


revision = "0017_delivery_agent_locations"
down_revision = "0016_retailer_settlement_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_agent_locations",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("accuracy_m", sa.Numeric(8, 2), nullable=False),
        sa.Column("heading_deg", sa.Numeric(6, 2), nullable=True),
        sa.Column("speed_mps", sa.Numeric(8, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_delivery_agent_location_latitude"),
        sa.CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_delivery_agent_location_longitude"),
        sa.CheckConstraint("accuracy_m >= 0 AND accuracy_m <= 100000", name="ck_delivery_agent_location_accuracy"),
        sa.CheckConstraint("heading_deg IS NULL OR (heading_deg >= 0 AND heading_deg < 360)", name="ck_delivery_agent_location_heading"),
        sa.CheckConstraint("speed_mps IS NULL OR (speed_mps >= 0 AND speed_mps <= 1000)", name="ck_delivery_agent_location_speed"),
        sa.ForeignKeyConstraint(["agent_id"], ["delivery_agents.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id"),
    )
    op.create_index("ix_delivery_agent_locations_updated_at", "delivery_agent_locations", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_delivery_agent_locations_updated_at", table_name="delivery_agent_locations")
    op.drop_table("delivery_agent_locations")
