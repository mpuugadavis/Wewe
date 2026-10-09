"""Add the delivery-fee components expected by the order model."""
from alembic import op
import sqlalchemy as sa

revision = "0023_order_delivery_discount_columns"
down_revision = "0022_retailer_pickup_location_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("gross_delivery_fee_ugx", sa.BigInteger(), server_default="0", nullable=False))
        batch.add_column(sa.Column("multi_retailer_discount_ugx", sa.BigInteger(), server_default="0", nullable=False))
        batch.add_column(sa.Column("multi_retailer_discount_percent", sa.Numeric(7, 3), server_default="0", nullable=False))

    op.execute(sa.text(
        "UPDATE orders SET gross_delivery_fee_ugx = delivery_fee_ugx, "
        "multi_retailer_discount_ugx = 0, multi_retailer_discount_percent = 0"
    ))

    with op.batch_alter_table("orders") as batch:
        batch.drop_constraint("ck_order_amounts", type_="check")
        batch.create_check_constraint(
            "ck_order_amounts",
            "subtotal_ugx >= 0 AND gross_delivery_fee_ugx >= 0 AND "
            "multi_retailer_discount_ugx >= 0 AND delivery_fee_ugx >= 0 AND total_ugx >= 0",
        )
        batch.create_check_constraint(
            "ck_order_delivery_discount_matches_components",
            "multi_retailer_discount_ugx <= gross_delivery_fee_ugx AND "
            "delivery_fee_ugx = gross_delivery_fee_ugx - multi_retailer_discount_ugx",
        )


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        batch.drop_constraint("ck_order_delivery_discount_matches_components", type_="check")
        batch.drop_constraint("ck_order_amounts", type_="check")
        batch.drop_column("multi_retailer_discount_percent")
        batch.drop_column("multi_retailer_discount_ugx")
        batch.drop_column("gross_delivery_fee_ugx")
        batch.create_check_constraint(
            "ck_order_amounts",
            "subtotal_ugx >= 0 AND delivery_fee_ugx >= 0 AND total_ugx >= 0",
        )
