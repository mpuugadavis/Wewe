"""Add delivery dispatch offers.

Revision ID: 0018
Revises: 0017_delivery_agent_locations
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_delivery_offers"
down_revision = "0017_delivery_agent_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_offers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("offer_sequence", sa.Integer(), nullable=False),
        sa.Column("offered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("distance_m", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING','ACCEPTED','REJECTED','EXPIRED','CANCELLED')",
            name="ck_delivery_offer_status",
        ),
        sa.CheckConstraint("distance_m >= 0", name="ck_delivery_offer_distance"),
        sa.ForeignKeyConstraint(["assignment_id"], ["delivery_assignments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["delivery_agents.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "agent_id", "offer_sequence", name="uq_delivery_offer_attempt"),
    )
    op.create_index("ix_delivery_offers_assignment_id", "delivery_offers", ["assignment_id"])
    op.create_index("ix_delivery_offers_agent_id", "delivery_offers", ["agent_id"])
    op.create_index("ix_delivery_offers_status", "delivery_offers", ["status"])
    op.create_index("ix_delivery_offers_agent_status", "delivery_offers", ["agent_id", "status"])
    op.create_index(
        "ix_delivery_offers_assignment_status_expiry",
        "delivery_offers",
        ["assignment_id", "status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_offers_assignment_status_expiry", table_name="delivery_offers")
    op.drop_index("ix_delivery_offers_agent_status", table_name="delivery_offers")
    op.drop_index("ix_delivery_offers_status", table_name="delivery_offers")
    op.drop_index("ix_delivery_offers_agent_id", table_name="delivery_offers")
    op.drop_index("ix_delivery_offers_assignment_id", table_name="delivery_offers")
    op.drop_table("delivery_offers")
