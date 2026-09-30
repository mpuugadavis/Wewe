"""Enforce online-only customer payment methods.

Revision ID: 0011_online_payment_methods
Revises: 0010_makerere_delivery_points
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa


revision = "0011_online_payment_methods"
down_revision = "0010_makerere_delivery_points"
branch_labels = None
depends_on = None


ONLINE_METHOD_CHECK = "method IN ('MTN_MOMO','AIRTEL_MONEY')"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # PostgreSQL supports NOT VALID for CHECK constraints. This prevents
        # historical legacy rows from blocking the migration while enforcing
        # the online-only rule for every new/updated payment row.
        op.execute(
            sa.text(
                "ALTER TABLE payments "
                "ADD CONSTRAINT ck_payment_method_online_only "
                f"CHECK ({ONLINE_METHOD_CHECK}) NOT VALID"
            )
        )
        return

    with op.batch_alter_table("payments") as batch_op:
        batch_op.create_check_constraint(
            "ck_payment_method_online_only",
            ONLINE_METHOD_CHECK,
        )


def downgrade() -> None:
    with op.batch_alter_table("payments") as batch_op:
        batch_op.drop_constraint("ck_payment_method_online_only", type_="check")
