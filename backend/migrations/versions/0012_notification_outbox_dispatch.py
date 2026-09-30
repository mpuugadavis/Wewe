"""Add durable notification outbox dispatch metadata.

Revision ID: 0012
Revises: 0011
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_notification_outbox_dispatch"
down_revision = "0011_online_payment_methods"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_outbox",
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notification_outbox",
        sa.Column("last_error", sa.String(length=1000), nullable=True),
    )
    op.create_index(
        "ix_notification_outbox_dispatch",
        "notification_outbox",
        ["status", "available_at"],
    )
    op.create_index(
        "ix_notification_outbox_available_at",
        "notification_outbox",
        ["available_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_outbox_available_at", table_name="notification_outbox")
    op.drop_index("ix_notification_outbox_dispatch", table_name="notification_outbox")
    op.drop_column("notification_outbox", "last_error")
    op.drop_column("notification_outbox", "locked_at")
