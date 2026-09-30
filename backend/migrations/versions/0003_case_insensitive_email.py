"""Case-insensitive email uniqueness.

Revision ID: 0003_case_insensitive_email
Revises: 0002_timestamp_defaults
Create Date: 2026-09-27

Scope
-----
Enforces case-insensitive email uniqueness at the database level so logically
identical email addresses (e.g. Davis@example.com and davis@example.com)
cannot bypass the uniqueness constraint through differing capitalization.

Implementation:
  * Creates a unique functional index 'uq_users_email_lower' on LOWER(email)
    where email IS NOT NULL.
  * Drops the legacy constraint 'users_email_key' (btree on raw email).

Downgrade:
  * Recreates the unique constraint 'users_email_key' on users(email).
  * Drops the unique functional index 'uq_users_email_lower'.
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_case_insensitive_email"
down_revision = "0002_timestamp_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create the replacement case-insensitive unique functional index first.
    op.create_index(
        "uq_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        sqlite_where=sa.text("email IS NOT NULL"),
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    # 2. Drop the redundant case-sensitive unique constraint.
    op.drop_constraint("users_email_key", "users", type_="unique")


def downgrade() -> None:
    # 1. Recreate the original case-sensitive unique constraint first.
    op.create_unique_constraint("users_email_key", "users", ["email"])
    # 2. Drop the case-insensitive unique functional index.
    op.drop_index(
        "uq_users_email_lower",
        table_name="users",
        sqlite_where=sa.text("email IS NOT NULL"),
        postgresql_where=sa.text("email IS NOT NULL"),
    )
