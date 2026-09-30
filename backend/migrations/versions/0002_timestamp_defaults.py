"""Add database-level timestamp defaults.

Revision ID: 0002_timestamp_defaults
Revises: 0001_initial
Create Date: 2026-09-27

Scope
-----
Adds a server default to the timestamp columns that previously relied only on
Python-side SQLAlchemy defaults, so a row inserted by any client (not just the
ORM) still receives a value:

  * 32 ``created_at`` columns
  * 24 ``updated_at`` columns

``created_at`` and ``updated_at`` are ``NOT NULL`` on every table that has them.
``SET DEFAULT`` does not alter nullability, rewrite rows, or touch indexes,
constraints, foreign keys or referential actions, so existing data and the rest
of the schema are untouched.

What a server default does and does not do
------------------------------------------
A server default supplies a value when a row is INSERTed. It does NOT change a
timestamp when an existing row is UPDATEd. ``updated_at`` therefore keeps
SQLAlchemy's ``onupdate=utcnow``, which is what stamps application-driven
updates. No trigger is added: a trigger would double-stamp every ORM write and
change existing behaviour, which is out of scope for this revision.

Out of scope
------------
``payment_events.received_at`` and ``notification_outbox.available_at`` are
deliberately not changed: they are not ``created_at``/``updated_at`` columns and
carry different semantics.
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_timestamp_defaults"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

# Tables whose created_at and updated_at both come from models.TimestampMixin.
CREATED_AT_AND_UPDATED_AT_TABLES = (
    "blocks",
    "campuses",
    "cart_items",
    "carts",
    "categories",
    "customer_profiles",
    "delivery_agents",
    "delivery_assignments",
    "delivery_points",
    "halls",
    "inventory",
    "orders",
    "payments",
    "pickup_points",
    "platform_settings",
    "product_images",
    "product_variants",
    "products",
    "retailer_fulfillments",
    "retailer_products",
    "retailers",
    "reviews",
    "universities",
    "users",
)

# Append-only tables that only record when a row was created.
CREATED_AT_ONLY_TABLES = (
    "audit_logs",
    "delivery_earnings",
    "delivery_events",
    "password_reset_tokens",
    "refresh_token_families",
    "refresh_tokens",
    "retailer_fulfillment_events",
    "wishlist_items",
)


def _timestamp_default():
    """Return the current-moment expression for the dialect being migrated."""
    if op.get_bind().dialect.name == "sqlite":
        return sa.text("CURRENT_TIMESTAMP")
    return sa.text("now()")


def _alter_timestamp(table: str, column: str, server_default) -> None:
    """Set a server default, or drop it when ``server_default`` is None."""
    options = {
        "existing_type": sa.DateTime(timezone=True),
        "existing_nullable": False,
        "server_default": server_default,
    }
    if op.get_bind().dialect.name == "sqlite":
        # SQLite cannot ALTER a column default, so batch mode recreates the table.
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(column, **options)
    else:
        op.alter_column(table, column, **options)


def upgrade() -> None:
    default = _timestamp_default()
    for table in CREATED_AT_AND_UPDATED_AT_TABLES:
        _alter_timestamp(table, "created_at", default)
        _alter_timestamp(table, "updated_at", default)
    for table in CREATED_AT_ONLY_TABLES:
        _alter_timestamp(table, "created_at", default)


def downgrade() -> None:
    for table in CREATED_AT_ONLY_TABLES:
        _alter_timestamp(table, "created_at", None)
    for table in CREATED_AT_AND_UPDATED_AT_TABLES:
        _alter_timestamp(table, "updated_at", None)
        _alter_timestamp(table, "created_at", None)
