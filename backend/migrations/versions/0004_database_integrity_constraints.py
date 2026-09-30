"""Add database integrity constraints for prices, contacts, and status values.

Revision ID: 0004_database_integrity_constraints
Revises: 0003_case_insensitive_email
Create Date: 2026-09-27

The required revision ID exceeds Alembic's default VARCHAR(32) tracking column.
Upgrade widens it; downgrade leaves the wider capacity because Alembic stores the
downgraded revision only after downgrade() returns.
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_database_integrity_constraints"
down_revision = "0003_case_insensitive_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_retailer_products_price_nonnegative",
        "retailer_products",
        "price_ugx >= 0",
    )
    op.create_check_constraint(
        "ck_retailer_phone_nonempty",
        "retailers",
        "replace(replace(replace(replace(replace(replace(phone, ' ', ''), '\t', ''), '\n', ''), '\r', ''), '\f', ''), '\v', '') <> ''",
    )
    op.create_check_constraint(
        "ck_retailer_status",
        "retailers",
        "status IN ('ACTIVE','INACTIVE')",
    )
    op.create_check_constraint(
        "ck_delivery_agent_verification",
        "delivery_agents",
        "verification_status IN ('PENDING','VERIFIED','REJECTED')",
    )
    op.create_check_constraint(
        "ck_delivery_agent_availability",
        "delivery_agents",
        "availability_status IN ('OFFLINE','AVAILABLE','BUSY')",
    )
    op.create_check_constraint(
        "ck_retailer_fulfillment_status",
        "retailer_fulfillments",
        "status IN ('PENDING','CONFIRMED','REJECTED','PREPARING','READY','OUT_FOR_DELIVERY','DELIVERED','CANCELLED')",
    )
    op.create_check_constraint(
        "ck_delivery_assignment_status",
        "delivery_assignments",
        "status IN ('UNASSIGNED','ACCEPTED','PICKED_UP','OUT_FOR_DELIVERY','DELIVERED','CANCELLED')",
    )
    op.create_check_constraint(
        "ck_delivery_earning_status",
        "delivery_earnings",
        "status IN ('PENDING','PAID')",
    )
    op.create_check_constraint(
        "ck_payment_event_status",
        "payment_events",
        "status IN ('SUCCESSFUL','FAILED','REFUNDED')",
    )
    op.create_check_constraint(
        "ck_review_moderation_status",
        "reviews",
        "moderation_status IN ('VISIBLE','HIDDEN')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_review_moderation_status", "reviews", type_="check")
    op.drop_constraint("ck_payment_event_status", "payment_events", type_="check")
    op.drop_constraint("ck_delivery_earning_status", "delivery_earnings", type_="check")
    op.drop_constraint("ck_delivery_assignment_status", "delivery_assignments", type_="check")
    op.drop_constraint("ck_retailer_fulfillment_status", "retailer_fulfillments", type_="check")
    op.drop_constraint("ck_delivery_agent_availability", "delivery_agents", type_="check")
    op.drop_constraint("ck_delivery_agent_verification", "delivery_agents", type_="check")
    op.drop_constraint("ck_retailer_status", "retailers", type_="check")
    op.drop_constraint("ck_retailer_phone_nonempty", "retailers", type_="check")
    op.drop_constraint("ck_retailer_products_price_nonnegative", "retailer_products", type_="check")
