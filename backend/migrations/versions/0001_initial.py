"""Initial normalized marketplace schema.

Frozen explicit DDL for the WEWE marketplace schema.

This revision replaces the original bootstrap, which built the schema from
``Base.metadata.create_all()``. The statements below describe the schema that is
actually present in the development database, written out explicitly so the
migration history is reproducible and reviewable and so that every later change
is a normal, incremental revision.

Do not edit this revision once it has been applied anywhere. Every further
schema change belongs in a new revision created with::

    alembic revision --autogenerate -m "describe change"
"""
import sqlalchemy as sa
from alembic import op


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Frozen from the live WEWE schema and reviewed before adoption.
    op.create_table('categories',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('slug', sa.String(length=120), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['parent_id'], ['categories.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_index(op.f('ix_categories_parent_id'), 'categories', ['parent_id'], unique=False)
    op.create_table('universities',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=180), nullable=False),
    sa.Column('slug', sa.String(length=180), nullable=False),
    sa.Column('country_code', sa.String(length=2), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name'),
    sa.UniqueConstraint('slug')
    )
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('phone', sa.String(length=20), nullable=True),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('phone_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("role IN ('CUSTOMER','RETAILER','DELIVERY_AGENT','ADMIN')", name='ck_users_role'),
    sa.CheckConstraint("status IN ('ACTIVE','PENDING','SUSPENDED','DEACTIVATED')", name='ck_users_status'),
    sa.CheckConstraint('email IS NOT NULL OR phone IS NOT NULL', name='ck_users_contact_required'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_index(op.f('ix_users_role'), 'users', ['role'], unique=False)
    op.create_index(op.f('ix_users_status'), 'users', ['status'], unique=False)
    op.create_index('uq_users_phone', 'users', ['phone'], unique=True, sqlite_where=sa.text('phone IS NOT NULL'), postgresql_where=sa.text('phone IS NOT NULL'))
    op.create_table('audit_logs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('resource_type', sa.String(length=80), nullable=False),
    sa.Column('resource_id', sa.String(length=80), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_actor_user_id'), 'audit_logs', ['actor_user_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    op.create_table('campuses',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('university_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=180), nullable=False),
    sa.Column('slug', sa.String(length=180), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['university_id'], ['universities.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('university_id', 'slug', name='uq_campus_university_slug')
    )
    op.create_index(op.f('ix_campuses_university_id'), 'campuses', ['university_id'], unique=False)
    op.create_table('carts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('customer_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('customer_id')
    )
    op.create_table('delivery_agents',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('phone', sa.String(length=20), nullable=False),
    sa.Column('verification_status', sa.String(length=20), nullable=False),
    sa.Column('availability_status', sa.String(length=20), nullable=False),
    sa.Column('transport_mode', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_index(op.f('ix_delivery_agents_availability_status'), 'delivery_agents', ['availability_status'], unique=False)
    op.create_table('notification_outbox',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('event_type', sa.String(length=80), nullable=False),
    sa.Column('channel', sa.String(length=20), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notification_outbox_event_type'), 'notification_outbox', ['event_type'], unique=False)
    op.create_index(op.f('ix_notification_outbox_status'), 'notification_outbox', ['status'], unique=False)
    op.create_index(op.f('ix_notification_outbox_user_id'), 'notification_outbox', ['user_id'], unique=False)
    op.create_table('password_reset_tokens',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_password_reset_tokens_expires_at'), 'password_reset_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_password_reset_tokens_user_id'), 'password_reset_tokens', ['user_id'], unique=False)
    op.create_table('platform_settings',
    sa.Column('key', sa.String(length=120), nullable=False),
    sa.Column('value', sa.JSON(), nullable=False),
    sa.Column('updated_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('products',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('category_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=220), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('DRAFT','ACTIVE','INACTIVE','REMOVED')", name='ck_product_status'),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_products_category_id'), 'products', ['category_id'], unique=False)
    op.create_index(op.f('ix_products_name'), 'products', ['name'], unique=False)
    op.create_index(op.f('ix_products_status'), 'products', ['status'], unique=False)
    op.create_table('refresh_token_families',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_version', sa.Integer(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_refresh_token_families_user_id'), 'refresh_token_families', ['user_id'], unique=False)
    op.create_table('verification_tokens',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('contact', sa.String(length=320), nullable=False),
    sa.Column('purpose', sa.String(length=12), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_verification_tokens_expires_at'), 'verification_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_verification_tokens_user_id'), 'verification_tokens', ['user_id'], unique=False)
    op.create_table('halls',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('campus_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=180), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['campus_id'], ['campuses.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('campus_id', 'name', name='uq_hall_campus_name')
    )
    op.create_index(op.f('ix_halls_campus_id'), 'halls', ['campus_id'], unique=False)
    op.create_table('product_images',
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('url', sa.String(length=1000), nullable=False),
    sa.Column('alt_text', sa.String(length=250), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_product_images_product_id'), 'product_images', ['product_id'], unique=False)
    op.create_table('product_variants',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('sku', sa.String(length=100), nullable=False),
    sa.Column('options', sa.JSON(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('product_id', 'sku', name='uq_variant_product_sku')
    )
    op.create_index(op.f('ix_product_variants_product_id'), 'product_variants', ['product_id'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('family_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['family_id'], ['refresh_token_families.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_refresh_tokens_expires_at'), 'refresh_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_family_id'), 'refresh_tokens', ['family_id'], unique=False)
    op.create_table('wishlist_items',
    sa.Column('customer_id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('customer_id', 'product_id'),
    sa.UniqueConstraint('customer_id', 'product_id', name='uq_wishlist_customer_product')
    )
    op.create_table('blocks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('hall_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['hall_id'], ['halls.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('hall_id', 'name', name='uq_block_hall_name')
    )
    op.create_index(op.f('ix_blocks_hall_id'), 'blocks', ['hall_id'], unique=False)
    op.create_table('delivery_points',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('campus_id', sa.Uuid(), nullable=False),
    sa.Column('hall_id', sa.Uuid(), nullable=True),
    sa.Column('block_id', sa.Uuid(), nullable=True),
    sa.Column('owner_user_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=180), nullable=False),
    sa.Column('directions', sa.String(length=500), nullable=True),
    sa.Column('is_private', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('ROOM','PICKUP_POINT','BUILDING','OTHER')", name='ck_delivery_point_kind'),
    sa.CheckConstraint('NOT is_private OR owner_user_id IS NOT NULL', name='ck_private_delivery_point_owner'),
    sa.ForeignKeyConstraint(['block_id'], ['blocks.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['campus_id'], ['campuses.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['hall_id'], ['halls.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_delivery_points_campus_id'), 'delivery_points', ['campus_id'], unique=False)
    op.create_index(op.f('ix_delivery_points_hall_id'), 'delivery_points', ['hall_id'], unique=False)
    op.create_index(op.f('ix_delivery_points_owner_user_id'), 'delivery_points', ['owner_user_id'], unique=False)
    op.create_table('customer_profiles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('preferred_delivery_point_id', sa.Uuid(), nullable=True),
    sa.Column('marketing_opt_in', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['preferred_delivery_point_id'], ['delivery_points.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('pickup_points',
    sa.Column('delivery_point_id', sa.Uuid(), nullable=False),
    sa.Column('contact_name', sa.String(length=120), nullable=True),
    sa.Column('contact_phone', sa.String(length=20), nullable=True),
    sa.Column('opening_hours', sa.JSON(), nullable=False),
    sa.Column('operating_status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['delivery_point_id'], ['delivery_points.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('delivery_point_id')
    )
    op.create_table('retailers',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('business_name', sa.String(length=180), nullable=False),
    sa.Column('slug', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('phone', sa.String(length=20), nullable=False),
    sa.Column('location_id', sa.Uuid(), nullable=True),
    sa.Column('verification_status', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("verification_status IN ('PENDING','VERIFIED','REJECTED')", name='ck_retailer_verification'),
    sa.ForeignKeyConstraint(['location_id'], ['delivery_points.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug'),
    sa.UniqueConstraint('user_id')
    )
    op.create_index(op.f('ix_retailers_business_name'), 'retailers', ['business_name'], unique=False)
    op.create_index(op.f('ix_retailers_status'), 'retailers', ['status'], unique=False)
    op.create_index(op.f('ix_retailers_verification_status'), 'retailers', ['verification_status'], unique=False)
    op.create_table('orders',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('order_number', sa.String(length=24), nullable=False),
    sa.Column('customer_id', sa.Uuid(), nullable=False),
    sa.Column('delivery_point_id', sa.Uuid(), nullable=True),
    sa.Column('pickup_point_id', sa.Uuid(), nullable=True),
    sa.Column('delivery_method', sa.String(length=20), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('subtotal_ugx', sa.BigInteger(), nullable=False),
    sa.Column('delivery_fee_ugx', sa.BigInteger(), nullable=False),
    sa.Column('total_ugx', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('payment_status', sa.String(length=20), nullable=False),
    sa.Column('idempotency_key', sa.String(length=100), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("delivery_method IN ('DELIVERY','PICKUP')", name='ck_order_delivery_method'),
    sa.CheckConstraint("payment_status IN ('UNPAID','PENDING','PAID','FAILED','REFUNDED')", name='ck_order_payment_status'),
    sa.CheckConstraint("status IN ('PENDING','CONFIRMED','PREPARING','READY','OUT_FOR_DELIVERY','DELIVERED','PARTIALLY_REJECTED','PARTIALLY_DELIVERED','CANCELLED','REJECTED','FAILED')", name='ck_order_status'),
    sa.CheckConstraint('subtotal_ugx >= 0 AND delivery_fee_ugx >= 0 AND total_ugx >= 0', name='ck_order_amounts'),
    sa.ForeignKeyConstraint(['customer_id'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['delivery_point_id'], ['delivery_points.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['pickup_point_id'], ['pickup_points.delivery_point_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('customer_id', 'idempotency_key', name='uq_order_idempotency')
    )
    op.create_index('ix_orders_created_status', 'orders', ['created_at', 'status'], unique=False)
    op.create_index(op.f('ix_orders_customer_id'), 'orders', ['customer_id'], unique=False)
    op.create_index(op.f('ix_orders_order_number'), 'orders', ['order_number'], unique=True)
    op.create_index(op.f('ix_orders_payment_status'), 'orders', ['payment_status'], unique=False)
    op.create_index(op.f('ix_orders_status'), 'orders', ['status'], unique=False)
    op.create_table('retailer_products',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('retailer_id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('sku', sa.String(length=100), nullable=True),
    sa.Column('price_ugx', sa.BigInteger(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['retailer_id'], ['retailers.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'product_id', 'retailer_id', name='uq_listing_inventory_reference'),
    sa.UniqueConstraint('retailer_id', 'product_id', name='uq_retailer_product')
    )
    op.create_index(op.f('ix_retailer_products_is_active'), 'retailer_products', ['is_active'], unique=False)
    op.create_index(op.f('ix_retailer_products_product_id'), 'retailer_products', ['product_id'], unique=False)
    op.create_index(op.f('ix_retailer_products_retailer_id'), 'retailer_products', ['retailer_id'], unique=False)
    op.create_table('cart_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('cart_id', sa.Uuid(), nullable=False),
    sa.Column('retailer_product_id', sa.Uuid(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('quantity > 0', name='ck_cart_item_quantity'),
    sa.ForeignKeyConstraint(['cart_id'], ['carts.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['retailer_product_id'], ['retailer_products.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cart_id', 'retailer_product_id', name='uq_cart_listing')
    )
    op.create_index(op.f('ix_cart_items_cart_id'), 'cart_items', ['cart_id'], unique=False)
    op.create_index(op.f('ix_cart_items_retailer_product_id'), 'cart_items', ['retailer_product_id'], unique=False)
    op.create_table('inventory',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('retailer_id', sa.Uuid(), nullable=True),
    sa.Column('retailer_product_id', sa.Uuid(), nullable=True),
    sa.Column('owner_type', sa.String(length=20), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('reserved_quantity', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("(owner_type = 'RETAILER' AND retailer_product_id IS NOT NULL AND retailer_id IS NOT NULL) OR (owner_type = 'PLATFORM' AND retailer_product_id IS NULL AND retailer_id IS NULL)", name='ck_inventory_owner_reference'),
    sa.CheckConstraint("owner_type IN ('RETAILER','PLATFORM')", name='ck_inventory_owner'),
    sa.CheckConstraint('quantity >= 0 AND reserved_quantity >= 0 AND reserved_quantity <= quantity', name='ck_inventory_quantities'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['retailer_id'], ['retailers.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['retailer_product_id', 'product_id', 'retailer_id'], ['retailer_products.id', 'retailer_products.product_id', 'retailer_products.retailer_id'], name='fk_inventory_listing_owner', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['retailer_product_id'], ['retailer_products.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('product_id', 'retailer_id', name='uq_inventory_product_owner'),
    sa.UniqueConstraint('retailer_product_id', name='uq_inventory_listing')
    )
    op.create_index(op.f('ix_inventory_product_id'), 'inventory', ['product_id'], unique=False)
    op.create_index('uq_platform_inventory_product', 'inventory', ['product_id'], unique=True, postgresql_where=sa.text("owner_type = 'PLATFORM'"), sqlite_where=sa.text("owner_type = 'PLATFORM'"))
    op.create_table('order_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=True),
    sa.Column('retailer_product_id', sa.Uuid(), nullable=True),
    sa.Column('retailer_id', sa.Uuid(), nullable=True),
    sa.Column('product_name', sa.String(length=220), nullable=False),
    sa.Column('sku_snapshot', sa.String(length=100), nullable=True),
    sa.Column('unit_price_ugx', sa.BigInteger(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('line_total_ugx', sa.BigInteger(), nullable=False),
    sa.CheckConstraint('quantity > 0 AND unit_price_ugx >= 0 AND line_total_ugx >= 0', name='ck_order_item_amounts'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['retailer_id'], ['retailers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['retailer_product_id'], ['retailer_products.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_order_items_order_id'), 'order_items', ['order_id'], unique=False)
    op.create_index(op.f('ix_order_items_retailer_id'), 'order_items', ['retailer_id'], unique=False)
    op.create_table('payments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('customer_id', sa.Uuid(), nullable=False),
    sa.Column('amount_ugx', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('method', sa.String(length=24), nullable=False),
    sa.Column('provider', sa.String(length=60), nullable=False),
    sa.Column('provider_reference', sa.String(length=180), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("amount_ugx > 0 AND currency = 'UGX'", name='ck_payment_amount_currency'),
    sa.CheckConstraint("status IN ('PENDING','SUCCESSFUL','FAILED','REFUNDED')", name='ck_payment_status'),
    sa.ForeignKeyConstraint(['customer_id'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider_reference')
    )
    op.create_index(op.f('ix_payments_customer_id'), 'payments', ['customer_id'], unique=False)
    op.create_index(op.f('ix_payments_order_id'), 'payments', ['order_id'], unique=False)
    op.create_index(op.f('ix_payments_status'), 'payments', ['status'], unique=False)
    op.create_table('retailer_fulfillments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('order_id', sa.Uuid(), nullable=False),
    sa.Column('retailer_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ready_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejection_reason', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['retailer_id'], ['retailers.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('order_id', 'retailer_id', name='uq_fulfillment_order_retailer')
    )
    op.create_index(op.f('ix_retailer_fulfillments_order_id'), 'retailer_fulfillments', ['order_id'], unique=False)
    op.create_index(op.f('ix_retailer_fulfillments_retailer_id'), 'retailer_fulfillments', ['retailer_id'], unique=False)
    op.create_index(op.f('ix_retailer_fulfillments_status'), 'retailer_fulfillments', ['status'], unique=False)
    op.create_table('delivery_assignments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('fulfillment_id', sa.Uuid(), nullable=False),
    sa.Column('agent_id', sa.Uuid(), nullable=True),
    sa.Column('pickup_point_id', sa.Uuid(), nullable=True),
    sa.Column('dropoff_point_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('picked_up_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('confirmation_code_hash', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['delivery_agents.user_id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['dropoff_point_id'], ['delivery_points.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['fulfillment_id'], ['retailer_fulfillments.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['pickup_point_id'], ['delivery_points.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('fulfillment_id', name='uq_delivery_fulfillment')
    )
    op.create_index(op.f('ix_delivery_assignments_agent_id'), 'delivery_assignments', ['agent_id'], unique=False)
    op.create_index(op.f('ix_delivery_assignments_fulfillment_id'), 'delivery_assignments', ['fulfillment_id'], unique=False)
    op.create_index(op.f('ix_delivery_assignments_status'), 'delivery_assignments', ['status'], unique=False)
    op.create_table('payment_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('payment_id', sa.Uuid(), nullable=False),
    sa.Column('provider_event_id', sa.String(length=180), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider_event_id')
    )
    op.create_index(op.f('ix_payment_events_payment_id'), 'payment_events', ['payment_id'], unique=False)
    op.create_table('retailer_fulfillment_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('fulfillment_id', sa.Uuid(), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('previous_status', sa.String(length=20), nullable=True),
    sa.Column('new_status', sa.String(length=20), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['fulfillment_id'], ['retailer_fulfillments.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_retailer_fulfillment_events_fulfillment_id'), 'retailer_fulfillment_events', ['fulfillment_id'], unique=False)
    op.create_table('reviews',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('customer_id', sa.Uuid(), nullable=False),
    sa.Column('order_item_id', sa.Uuid(), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=False),
    sa.Column('body', sa.String(length=2000), nullable=True),
    sa.Column('moderation_status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('rating BETWEEN 1 AND 5', name='ck_review_rating'),
    sa.ForeignKeyConstraint(['customer_id'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_item_id'], ['order_items.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('order_item_id', name='uq_review_order_item')
    )
    op.create_index(op.f('ix_reviews_customer_id'), 'reviews', ['customer_id'], unique=False)
    op.create_index(op.f('ix_reviews_product_id'), 'reviews', ['product_id'], unique=False)
    op.create_table('delivery_earnings',
    sa.Column('assignment_id', sa.Uuid(), nullable=False),
    sa.Column('agent_id', sa.Uuid(), nullable=False),
    sa.Column('amount_ugx', sa.BigInteger(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('payout_reference', sa.String(length=180), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['agent_id'], ['delivery_agents.user_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['assignment_id'], ['delivery_assignments.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('assignment_id'),
    sa.UniqueConstraint('payout_reference')
    )
    op.create_index(op.f('ix_delivery_earnings_agent_id'), 'delivery_earnings', ['agent_id'], unique=False)
    op.create_index(op.f('ix_delivery_earnings_status'), 'delivery_earnings', ['status'], unique=False)
    op.create_table('delivery_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('assignment_id', sa.Uuid(), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('previous_status', sa.String(length=24), nullable=True),
    sa.Column('new_status', sa.String(length=24), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['assignment_id'], ['delivery_assignments.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_delivery_events_assignment_id'), 'delivery_events', ['assignment_id'], unique=False)
    # End of frozen initial schema.


def downgrade() -> None:
    # Frozen from the live WEWE schema and reviewed before adoption.
    op.drop_index(op.f('ix_delivery_events_assignment_id'), table_name='delivery_events')
    op.drop_table('delivery_events')
    op.drop_index(op.f('ix_delivery_earnings_status'), table_name='delivery_earnings')
    op.drop_index(op.f('ix_delivery_earnings_agent_id'), table_name='delivery_earnings')
    op.drop_table('delivery_earnings')
    op.drop_index(op.f('ix_reviews_product_id'), table_name='reviews')
    op.drop_index(op.f('ix_reviews_customer_id'), table_name='reviews')
    op.drop_table('reviews')
    op.drop_index(op.f('ix_retailer_fulfillment_events_fulfillment_id'), table_name='retailer_fulfillment_events')
    op.drop_table('retailer_fulfillment_events')
    op.drop_index(op.f('ix_payment_events_payment_id'), table_name='payment_events')
    op.drop_table('payment_events')
    op.drop_index(op.f('ix_delivery_assignments_status'), table_name='delivery_assignments')
    op.drop_index(op.f('ix_delivery_assignments_fulfillment_id'), table_name='delivery_assignments')
    op.drop_index(op.f('ix_delivery_assignments_agent_id'), table_name='delivery_assignments')
    op.drop_table('delivery_assignments')
    op.drop_index(op.f('ix_retailer_fulfillments_status'), table_name='retailer_fulfillments')
    op.drop_index(op.f('ix_retailer_fulfillments_retailer_id'), table_name='retailer_fulfillments')
    op.drop_index(op.f('ix_retailer_fulfillments_order_id'), table_name='retailer_fulfillments')
    op.drop_table('retailer_fulfillments')
    op.drop_index(op.f('ix_payments_status'), table_name='payments')
    op.drop_index(op.f('ix_payments_order_id'), table_name='payments')
    op.drop_index(op.f('ix_payments_customer_id'), table_name='payments')
    op.drop_table('payments')
    op.drop_index(op.f('ix_order_items_retailer_id'), table_name='order_items')
    op.drop_index(op.f('ix_order_items_order_id'), table_name='order_items')
    op.drop_table('order_items')
    op.drop_index('uq_platform_inventory_product', table_name='inventory', postgresql_where=sa.text("owner_type = 'PLATFORM'"), sqlite_where=sa.text("owner_type = 'PLATFORM'"))
    op.drop_index(op.f('ix_inventory_product_id'), table_name='inventory')
    op.drop_table('inventory')
    op.drop_index(op.f('ix_cart_items_retailer_product_id'), table_name='cart_items')
    op.drop_index(op.f('ix_cart_items_cart_id'), table_name='cart_items')
    op.drop_table('cart_items')
    op.drop_index(op.f('ix_retailer_products_retailer_id'), table_name='retailer_products')
    op.drop_index(op.f('ix_retailer_products_product_id'), table_name='retailer_products')
    op.drop_index(op.f('ix_retailer_products_is_active'), table_name='retailer_products')
    op.drop_table('retailer_products')
    op.drop_index(op.f('ix_orders_status'), table_name='orders')
    op.drop_index(op.f('ix_orders_payment_status'), table_name='orders')
    op.drop_index(op.f('ix_orders_order_number'), table_name='orders')
    op.drop_index(op.f('ix_orders_customer_id'), table_name='orders')
    op.drop_index('ix_orders_created_status', table_name='orders')
    op.drop_table('orders')
    op.drop_index(op.f('ix_retailers_verification_status'), table_name='retailers')
    op.drop_index(op.f('ix_retailers_status'), table_name='retailers')
    op.drop_index(op.f('ix_retailers_business_name'), table_name='retailers')
    op.drop_table('retailers')
    op.drop_table('pickup_points')
    op.drop_table('customer_profiles')
    op.drop_index(op.f('ix_delivery_points_owner_user_id'), table_name='delivery_points')
    op.drop_index(op.f('ix_delivery_points_hall_id'), table_name='delivery_points')
    op.drop_index(op.f('ix_delivery_points_campus_id'), table_name='delivery_points')
    op.drop_table('delivery_points')
    op.drop_index(op.f('ix_blocks_hall_id'), table_name='blocks')
    op.drop_table('blocks')
    op.drop_table('wishlist_items')
    op.drop_index(op.f('ix_refresh_tokens_family_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_expires_at'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index(op.f('ix_product_variants_product_id'), table_name='product_variants')
    op.drop_table('product_variants')
    op.drop_index(op.f('ix_product_images_product_id'), table_name='product_images')
    op.drop_table('product_images')
    op.drop_index(op.f('ix_halls_campus_id'), table_name='halls')
    op.drop_table('halls')
    op.drop_index(op.f('ix_verification_tokens_user_id'), table_name='verification_tokens')
    op.drop_index(op.f('ix_verification_tokens_expires_at'), table_name='verification_tokens')
    op.drop_table('verification_tokens')
    op.drop_index(op.f('ix_refresh_token_families_user_id'), table_name='refresh_token_families')
    op.drop_table('refresh_token_families')
    op.drop_index(op.f('ix_products_status'), table_name='products')
    op.drop_index(op.f('ix_products_name'), table_name='products')
    op.drop_index(op.f('ix_products_category_id'), table_name='products')
    op.drop_table('products')
    op.drop_table('platform_settings')
    op.drop_index(op.f('ix_password_reset_tokens_user_id'), table_name='password_reset_tokens')
    op.drop_index(op.f('ix_password_reset_tokens_expires_at'), table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
    op.drop_index(op.f('ix_notification_outbox_user_id'), table_name='notification_outbox')
    op.drop_index(op.f('ix_notification_outbox_status'), table_name='notification_outbox')
    op.drop_index(op.f('ix_notification_outbox_event_type'), table_name='notification_outbox')
    op.drop_table('notification_outbox')
    op.drop_index(op.f('ix_delivery_agents_availability_status'), table_name='delivery_agents')
    op.drop_table('delivery_agents')
    op.drop_table('carts')
    op.drop_index(op.f('ix_campuses_university_id'), table_name='campuses')
    op.drop_table('campuses')
    op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_actor_user_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index('uq_users_phone', table_name='users', sqlite_where=sa.text('phone IS NOT NULL'), postgresql_where=sa.text('phone IS NOT NULL'))
    op.drop_index(op.f('ix_users_status'), table_name='users')
    op.drop_index(op.f('ix_users_role'), table_name='users')
    op.drop_table('users')
    op.drop_table('universities')
    op.drop_index(op.f('ix_categories_parent_id'), table_name='categories')
    op.drop_table('categories')
    # End of frozen initial schema.
