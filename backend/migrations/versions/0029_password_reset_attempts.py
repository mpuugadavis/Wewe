"""Persist guessing limits for six-digit password recovery codes."""
from alembic import op
import sqlalchemy as sa

revision = "0029_password_reset_attempts"
down_revision = "0028_one_active_rider_delivery"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("password_reset_tokens", sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("password_reset_tokens", "failed_attempts")
