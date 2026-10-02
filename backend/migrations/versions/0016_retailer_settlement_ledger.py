"""Add retailer settlement ledger foundation.

Revision ID: 0016
Revises: 0015_product_media_local_url
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_retailer_settlement_ledger"
down_revision = "0015_product_media_local_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retailer_payment_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("fulfillment_id", sa.Uuid(), nullable=False),
        sa.Column("retailer_id", sa.Uuid(), nullable=False),
        sa.Column("amount_ugx", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount_ugx > 0", name="ck_retailer_payment_allocation_amount"),
        sa.CheckConstraint("currency = 'UGX'", name="ck_retailer_payment_allocation_currency"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["fulfillment_id"], ["retailer_fulfillments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id", "fulfillment_id", name="uq_retailer_payment_allocation_payment_fulfillment"),
    )
    op.create_index("ix_retailer_payment_allocations_payment_id", "retailer_payment_allocations", ["payment_id"])
    op.create_index("ix_retailer_payment_allocations_fulfillment_id", "retailer_payment_allocations", ["fulfillment_id"])
    op.create_index("ix_retailer_payment_allocations_retailer_id", "retailer_payment_allocations", ["retailer_id"])

    op.create_table(
        "retailer_payable_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("retailer_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("fulfillment_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=True),
        sa.Column("entry_type", sa.String(length=10), nullable=False),
        sa.Column("amount_ugx", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reason", sa.String(length=60), nullable=False),
        sa.Column("source_reference", sa.String(length=180), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("entry_type IN ('CREDIT','DEBIT')", name="ck_retailer_payable_entry_type"),
        sa.CheckConstraint("amount_ugx > 0", name="ck_retailer_payable_entry_amount"),
        sa.CheckConstraint("currency = 'UGX'", name="ck_retailer_payable_entry_currency"),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["fulfillment_id"], ["retailer_fulfillments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_reference", name="uq_retailer_payable_entry_source_reference"),
    )
    op.create_index("ix_retailer_payable_entries_retailer_id", "retailer_payable_entries", ["retailer_id"])
    op.create_index("ix_retailer_payable_entries_order_id", "retailer_payable_entries", ["order_id"])
    op.create_index("ix_retailer_payable_entries_fulfillment_id", "retailer_payable_entries", ["fulfillment_id"])
    op.create_index("ix_retailer_payable_entries_payment_id", "retailer_payable_entries", ["payment_id"])
    op.create_index("ix_retailer_payable_entries_retailer_created", "retailer_payable_entries", ["retailer_id", "created_at"])

    op.create_table(
        "retailer_settlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("retailer_id", sa.Uuid(), nullable=False),
        sa.Column("amount_ugx", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("settlement_reference", sa.String(length=180), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("payout_reference", sa.String(length=180), nullable=True),
        sa.Column("authorized_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT','SUBMITTED','SETTLED','FAILED','REVIEW_REQUIRED')", name="ck_retailer_settlement_status"),
        sa.CheckConstraint("amount_ugx > 0", name="ck_retailer_settlement_amount"),
        sa.CheckConstraint("currency = 'UGX'", name="ck_retailer_settlement_currency"),
        sa.ForeignKeyConstraint(["retailer_id"], ["retailers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorized_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("settlement_reference", name="uq_retailer_settlement_reference"),
        sa.UniqueConstraint("idempotency_key", name="uq_retailer_settlement_idempotency"),
        sa.UniqueConstraint("payout_reference", name="uq_retailer_settlement_payout_reference"),
    )
    op.create_index("ix_retailer_settlements_retailer_id", "retailer_settlements", ["retailer_id"])
    op.create_index("ix_retailer_settlements_status", "retailer_settlements", ["status"])

    op.create_table(
        "retailer_settlement_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("settlement_id", sa.Uuid(), nullable=False),
        sa.Column("payable_entry_id", sa.Uuid(), nullable=False),
        sa.Column("amount_ugx", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount_ugx > 0", name="ck_retailer_settlement_line_amount"),
        sa.CheckConstraint("currency = 'UGX'", name="ck_retailer_settlement_line_currency"),
        sa.ForeignKeyConstraint(["settlement_id"], ["retailer_settlements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payable_entry_id"], ["retailer_payable_entries.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("settlement_id", "payable_entry_id", name="uq_retailer_settlement_line_entry"),
    )
    op.create_index("ix_retailer_settlement_lines_settlement_id", "retailer_settlement_lines", ["settlement_id"])
    op.create_index("ix_retailer_settlement_lines_payable_entry_id", "retailer_settlement_lines", ["payable_entry_id"])


def downgrade() -> None:
    op.drop_table("retailer_settlement_lines")
    op.drop_table("retailer_settlements")
    op.drop_table("retailer_payable_entries")
    op.drop_table("retailer_payment_allocations")
