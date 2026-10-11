from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('CUSTOMER','RETAILER','DELIVERY_AGENT','ADMIN')", name="ck_users_role"),
        CheckConstraint("status IN ('ACTIVE','PENDING','SUSPENDED','DEACTIVATED')", name="ck_users_status"),
        CheckConstraint("email IS NOT NULL OR phone IS NOT NULL", name="ck_users_contact_required"),
        Index("uq_users_phone", "phone", unique=True, sqlite_where=text("phone IS NOT NULL"),
              postgresql_where=text("phone IS NOT NULL")),
        Index("uq_users_email_lower", func.lower(text("email")), unique=True,
              sqlite_where=text("email IS NOT NULL"), postgresql_where=text("email IS NOT NULL")),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False, index=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class CustomerProfile(TimestampMixin, Base):
    __tablename__ = "customer_profiles"
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    preferred_delivery_point_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("delivery_points.id", ondelete="SET NULL"))
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class University(TimestampMixin, Base):
    __tablename__ = "universities"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), default="UG", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Campus(TimestampMixin, Base):
    __tablename__ = "campuses"
    __table_args__ = (UniqueConstraint("university_id", "slug", name="uq_campus_university_slug"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    university_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("universities.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Hall(TimestampMixin, Base):
    __tablename__ = "halls"
    __table_args__ = (UniqueConstraint("campus_id", "name", name="uq_hall_campus_name"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    campus_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("campuses.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="HALL", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Block(TimestampMixin, Base):
    __tablename__ = "blocks"
    __table_args__ = (UniqueConstraint("hall_id", "name", name="uq_block_hall_name"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    hall_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("halls.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class DeliveryPoint(TimestampMixin, Base):
    __tablename__ = "delivery_points"
    __table_args__ = (
        CheckConstraint("kind IN ('ROOM','PICKUP_POINT','BUILDING','OTHER')", name="ck_delivery_point_kind"),
        CheckConstraint("NOT is_private OR owner_user_id IS NOT NULL", name="ck_private_delivery_point_owner"),
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="ck_delivery_point_latitude_range",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="ck_delivery_point_longitude_range",
        ),
        CheckConstraint("(latitude IS NULL) = (longitude IS NULL)", name="ck_delivery_point_coordinate_pair"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    campus_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("campuses.id", ondelete="RESTRICT"), index=True)
    hall_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("halls.id", ondelete="RESTRICT"), index=True)
    block_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("blocks.id", ondelete="RESTRICT"))
    owner_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    directions: Mapped[str | None] = mapped_column(String(500))
    #: Optional WGS84 coordinates. When both are present the routing service
    #: uses them directly; otherwise the address is geocoded (COM-FEE-004).
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    #: Optional Google Place ID for authoritative routing/access-point resolution.
    google_place_id: Mapped[str | None] = mapped_column(String(300))
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PickupPoint(TimestampMixin, Base):
    __tablename__ = "pickup_points"
    __table_args__ = (
        CheckConstraint(
            "operating_status IN ('OPEN','CLOSED','TEMPORARILY_UNAVAILABLE')",
            name="ck_pickup_point_operating_status",
        ),
    )
    delivery_point_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("delivery_points.id", ondelete="RESTRICT"), primary_key=True)
    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    opening_hours: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    operating_status: Mapped[str] = mapped_column(String(32), default="OPEN", nullable=False)


class Retailer(TimestampMixin, Base):
    __tablename__ = "retailers"
    __table_args__ = (
        CheckConstraint(
            "replace(replace(replace(replace(replace(replace(phone, ' ', ''), '\t', ''), '\n', ''), '\r', ''), '\f', ''), '\v', '') <> ''",
            name="ck_retailer_phone_nonempty",
        ),
        CheckConstraint("verification_status IN ('PENDING','VERIFIED','REJECTED')", name="ck_retailer_verification"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_retailer_status"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), unique=True)
    business_name: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    location_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("delivery_points.id", ondelete="SET NULL"))
    verification_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False, index=True)


class DeliveryAgent(TimestampMixin, Base):
    __tablename__ = "delivery_agents"
    __table_args__ = (
        CheckConstraint("verification_status IN ('PENDING','VERIFIED','REJECTED')", name="ck_delivery_agent_verification"),
        CheckConstraint("availability_status IN ('OFFLINE','AVAILABLE','BUSY')", name="ck_delivery_agent_availability"),
    )
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    availability_status: Mapped[str] = mapped_column(String(20), default="OFFLINE", nullable=False, index=True)
    transport_mode: Mapped[str | None] = mapped_column(String(40))


class DeliveryAgentLocation(TimestampMixin, Base):
    __tablename__ = "delivery_agent_locations"
    __table_args__ = (
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_delivery_agent_location_latitude"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_delivery_agent_location_longitude"),
        CheckConstraint("accuracy_m >= 0 AND accuracy_m <= 100000", name="ck_delivery_agent_location_accuracy"),
        CheckConstraint("heading_deg IS NULL OR (heading_deg >= 0 AND heading_deg < 360)", name="ck_delivery_agent_location_heading"),
        CheckConstraint("speed_mps IS NULL OR (speed_mps >= 0 AND speed_mps <= 1000)", name="ck_delivery_agent_location_speed"),
        Index("ix_delivery_agent_locations_updated_at", "updated_at"),
    )
    agent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("delivery_agents.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    accuracy_m: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    heading_deg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    speed_mps: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))


class DeliveryOffer(TimestampMixin, Base):
    __tablename__ = "delivery_offers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','ACCEPTED','REJECTED','EXPIRED','CANCELLED')",
            name="ck_delivery_offer_status",
        ),
        CheckConstraint("distance_m >= 0", name="ck_delivery_offer_distance"),
        UniqueConstraint("assignment_id", "agent_id", "offer_sequence", name="uq_delivery_offer_attempt"),
        Index("ix_delivery_offers_agent_status", "agent_id", "status"),
        Index("ix_delivery_offers_assignment_status_expiry", "assignment_id", "status", "expires_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("delivery_assignments.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("delivery_agents.user_id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False, index=True)
    offer_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    offered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    distance_m: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class Category(TimestampMixin, Base):
    __tablename__ = "categories"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    parent_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (CheckConstraint("status IN ('DRAFT','ACTIVE','INACTIVE','REMOVED')", name="ck_product_status"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    category_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False, index=True)


class WorkerHealth(Base):
    __tablename__ = "worker_health"
    __table_args__ = (
        CheckConstraint(
            "status IN ('STARTING','RUNNING','HEALTHY','FAILING','STOPPED')",
            name="ck_worker_health_status",
        ),
        CheckConstraint(
            "last_duration_ms IS NULL OR last_duration_ms >= 0",
            name="ck_worker_health_duration",
        ),
        CheckConstraint(
            "last_processed >= 0 AND last_scanned >= 0 AND last_candidates >= 0 "
            "AND last_deleted >= 0 AND last_skipped >= 0 AND last_failed >= 0",
            name="ck_worker_health_counts",
        ),
    )

    worker_name: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_duration_ms: Mapped[int | None] = mapped_column(Integer)
    last_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_scanned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_candidates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_deleted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(1000))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ProductImage(TimestampMixin, Base):
    __tablename__ = "product_images"
    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="ck_product_images_sort_order_nonnegative"),
        CheckConstraint(
            "url LIKE 'https://%' OR url LIKE 'http://localhost:%' OR url LIKE 'http://127.0.0.1:%'",
            name="ck_product_images_https_url",
        ),
        UniqueConstraint("product_id", "url", name="uq_product_image_product_url"),
    )
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), index=True)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(250))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(500), unique=True)
    content_type: Mapped[str | None] = mapped_column(String(50))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)


class ProductVariant(TimestampMixin, Base):
    __tablename__ = "product_variants"
    __table_args__ = (UniqueConstraint("product_id", "sku", name="uq_variant_product_sku"),)
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class RetailerProduct(TimestampMixin, Base):
    __tablename__ = "retailer_products"
    __table_args__ = (
        UniqueConstraint("retailer_id", "product_id", name="uq_retailer_product"),
        UniqueConstraint("id", "product_id", "retailer_id", name="uq_listing_inventory_reference"),
        CheckConstraint("price_ugx >= 0", name="ck_retailer_products_price_nonnegative"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    retailer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailers.id", ondelete="RESTRICT"), index=True)
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    sku: Mapped[str | None] = mapped_column(String(100))
    price_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class Inventory(TimestampMixin, Base):
    __tablename__ = "inventory"
    __table_args__ = (
        CheckConstraint("owner_type IN ('RETAILER','PLATFORM')", name="ck_inventory_owner"),
        CheckConstraint("quantity >= 0 AND reserved_quantity >= 0 AND reserved_quantity <= quantity", name="ck_inventory_quantities"),
        CheckConstraint("(owner_type = 'RETAILER' AND retailer_product_id IS NOT NULL AND retailer_id IS NOT NULL) OR (owner_type = 'PLATFORM' AND retailer_product_id IS NULL AND retailer_id IS NULL)", name="ck_inventory_owner_reference"),
        ForeignKeyConstraint(
            ["retailer_product_id", "product_id", "retailer_id"],
            ["retailer_products.id", "retailer_products.product_id", "retailer_products.retailer_id"],
            ondelete="RESTRICT",
            name="fk_inventory_listing_owner",
        ),
        UniqueConstraint("retailer_product_id", name="uq_inventory_listing"),
        UniqueConstraint("product_id", "retailer_id", name="uq_inventory_product_owner"),
        Index("uq_platform_inventory_product", "product_id", unique=True, postgresql_where=text("owner_type = 'PLATFORM'"), sqlite_where=text("owner_type = 'PLATFORM'")),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    retailer_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailers.id", ondelete="RESTRICT"))
    retailer_product_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailer_products.id", ondelete="RESTRICT"))
    owner_type: Mapped[str] = mapped_column(String(20), default="RETAILER", nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Cart(TimestampMixin, Base):
    __tablename__ = "carts"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True)


class CartItem(TimestampMixin, Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("cart_id", "retailer_product_id", name="uq_cart_listing"), CheckConstraint("quantity > 0", name="ck_cart_item_quantity"))
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    cart_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), index=True)
    retailer_product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailer_products.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("customer_id", "idempotency_key", name="uq_order_idempotency"),
        CheckConstraint("delivery_method IN ('DELIVERY','PICKUP')", name="ck_order_delivery_method"),
        CheckConstraint(
            "(delivery_method = 'DELIVERY' AND delivery_point_id IS NOT NULL AND pickup_point_id IS NULL) OR "
            "(delivery_method = 'PICKUP' AND delivery_point_id IS NULL AND pickup_point_id IS NOT NULL)",
            name="ck_order_destination_matches_method",
        ),
        CheckConstraint("status IN ('PENDING','CONFIRMED','PREPARING','READY','OUT_FOR_DELIVERY','DELIVERED','PARTIALLY_REJECTED','PARTIALLY_DELIVERED','CANCELLED','REJECTED','FAILED')", name="ck_order_status"),
        CheckConstraint("payment_status IN ('UNPAID','PENDING','PAID','FAILED','REFUNDED')", name="ck_order_payment_status"),
        CheckConstraint("subtotal_ugx >= 0 AND gross_delivery_fee_ugx >= 0 AND multi_retailer_discount_ugx >= 0 AND delivery_fee_ugx >= 0 AND total_ugx >= 0 AND platform_commission_ugx >= 0", name="ck_order_amounts"),
        CheckConstraint("multi_retailer_discount_ugx <= gross_delivery_fee_ugx AND delivery_fee_ugx = gross_delivery_fee_ugx - multi_retailer_discount_ugx", name="ck_order_delivery_discount_matches_components"),
        CheckConstraint("total_ugx = subtotal_ugx + delivery_fee_ugx", name="ck_order_total_matches_components"),
        Index("ix_orders_created_status", "created_at", "status"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    order_number: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)
    customer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    delivery_point_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("delivery_points.id", ondelete="RESTRICT"))
    pickup_point_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("pickup_points.delivery_point_id", ondelete="RESTRICT"))
    delivery_method: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="UGX", nullable=False)
    subtotal_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gross_delivery_fee_ugx: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    multi_retailer_discount_ugx: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    multi_retailer_discount_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), default=Decimal("0"), server_default="0", nullable=False)
    delivery_fee_ugx: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    platform_commission_percent: Mapped[Decimal] = mapped_column(Numeric(7, 3), default=Decimal("8"), server_default="8", nullable=False)
    platform_commission_ugx: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False, index=True)
    payment_status: Mapped[str] = mapped_column(String(20), default="UNPAID", nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0 AND unit_price_ugx >= 0 AND line_total_ugx >= 0", name="ck_order_item_amounts"),
        CheckConstraint(
            "line_total_ugx = unit_price_ugx * quantity",
            name="ck_order_item_total_matches_price",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"))
    retailer_product_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailer_products.id", ondelete="SET NULL"))
    retailer_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailers.id", ondelete="SET NULL"), index=True)
    product_name: Mapped[str] = mapped_column(String(220), nullable=False)
    sku_snapshot: Mapped[str | None] = mapped_column(String(100))
    unit_price_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RetailerFulfillment(TimestampMixin, Base):
    __tablename__ = "retailer_fulfillments"
    __table_args__ = (
        UniqueConstraint("order_id", "retailer_id", name="uq_fulfillment_order_retailer"),
        CheckConstraint(
            "status IN ('PENDING','CONFIRMED','REJECTED','PREPARING','READY','OUT_FOR_DELIVERY','DELIVERED','CANCELLED')",
            name="ck_retailer_fulfillment_status",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    retailer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailers.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(String(300))


class RetailerFulfillmentEvent(Base):
    __tablename__ = "retailer_fulfillment_events"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    fulfillment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailer_fulfillments.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    previous_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)


class DeliveryAssignment(TimestampMixin, Base):
    __tablename__ = "delivery_assignments"
    __table_args__ = (
        UniqueConstraint("fulfillment_id", name="uq_delivery_fulfillment"),
        CheckConstraint(
            "status IN ('UNASSIGNED','ACCEPTED','PICKED_UP','OUT_FOR_DELIVERY','DELIVERED','CANCELLED')",
            name="ck_delivery_assignment_status",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    fulfillment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailer_fulfillments.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("delivery_agents.user_id", ondelete="SET NULL"), index=True)
    pickup_point_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("delivery_points.id", ondelete="SET NULL"))
    dropoff_point_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("delivery_points.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(24), default="UNASSIGNED", nullable=False, index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_code_hash: Mapped[str | None] = mapped_column(String(128))


class DeliveryEvent(Base):
    __tablename__ = "delivery_events"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("delivery_assignments.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    previous_status: Mapped[str | None] = mapped_column(String(24))
    new_status: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)



class RetailerPaymentAllocation(Base):
    """Immutable attribution of a captured payment to a retailer fulfillment."""
    __tablename__ = "retailer_payment_allocations"
    __table_args__ = (
        CheckConstraint("amount_ugx > 0", name="ck_retailer_payment_allocation_amount"),
        CheckConstraint("currency = 'UGX'", name="ck_retailer_payment_allocation_currency"),
        UniqueConstraint("payment_id", "fulfillment_id", name="uq_retailer_payment_allocation_payment_fulfillment"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    payment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("payments.id", ondelete="RESTRICT"), index=True)
    fulfillment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailer_fulfillments.id", ondelete="RESTRICT"), index=True)
    retailer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailers.id", ondelete="RESTRICT"), index=True)
    amount_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="UGX", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)


class RetailerPayableEntry(Base):
    """Auditable credit/debit entry contributing to a retailer payable balance."""
    __tablename__ = "retailer_payable_entries"
    __table_args__ = (
        CheckConstraint("entry_type IN ('CREDIT','DEBIT')", name="ck_retailer_payable_entry_type"),
        CheckConstraint("amount_ugx > 0", name="ck_retailer_payable_entry_amount"),
        CheckConstraint("currency = 'UGX'", name="ck_retailer_payable_entry_currency"),
        Index("ix_retailer_payable_entries_retailer_created", "retailer_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    retailer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailers.id", ondelete="RESTRICT"), index=True)
    order_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
    fulfillment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailer_fulfillments.id", ondelete="RESTRICT"), index=True)
    payment_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("payments.id", ondelete="RESTRICT"), index=True)
    entry_type: Mapped[str] = mapped_column(String(10), nullable=False)
    amount_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="UGX", nullable=False)
    reason: Mapped[str] = mapped_column(String(60), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(180), unique=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)


class RetailerSettlement(Base):
    """Idempotent settlement instruction; submission is not settlement confirmation."""
    __tablename__ = "retailer_settlements"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT','SUBMITTED','SETTLED','FAILED','REVIEW_REQUIRED')", name="ck_retailer_settlement_status"),
        CheckConstraint("amount_ugx > 0", name="ck_retailer_settlement_amount"),
        CheckConstraint("currency = 'UGX'", name="ck_retailer_settlement_currency"),
        UniqueConstraint("settlement_reference", name="uq_retailer_settlement_reference"),
        UniqueConstraint("idempotency_key", name="uq_retailer_settlement_idempotency"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    retailer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailers.id", ondelete="RESTRICT"), index=True)
    amount_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="UGX", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False, index=True)
    settlement_reference: Mapped[str] = mapped_column(String(180), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    payout_reference: Mapped[str | None] = mapped_column(String(180), unique=True)
    authorized_by_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)


class RetailerSettlementLine(Base):
    """Links a settlement to the exact payable entries it consumes."""
    __tablename__ = "retailer_settlement_lines"
    __table_args__ = (
        CheckConstraint("amount_ugx > 0", name="ck_retailer_settlement_line_amount"),
        CheckConstraint("currency = 'UGX'", name="ck_retailer_settlement_line_currency"),
        UniqueConstraint("settlement_id", "payable_entry_id", name="uq_retailer_settlement_line_entry"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    settlement_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailer_settlements.id", ondelete="CASCADE"), index=True)
    payable_entry_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("retailer_payable_entries.id", ondelete="RESTRICT"), index=True)
    amount_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="UGX", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)


class DeliveryEarning(Base):
    __tablename__ = "delivery_earnings"
    __table_args__ = (CheckConstraint("status IN ('PENDING','PAID')", name="ck_delivery_earning_status"),)
    assignment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("delivery_assignments.id", ondelete="RESTRICT"), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("delivery_agents.user_id", ondelete="RESTRICT"), index=True)
    amount_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="UGX", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False, index=True)
    # A single payout reference may cover many rider earnings in one batch.
    payout_reference: Mapped[str | None] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeliveryPayoutBatch(Base):
    """Controlled payout instruction grouping rider earnings."""
    __tablename__ = "delivery_payout_batches"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT','SUBMITTED','SETTLED','FAILED','REVIEW_REQUIRED')", name="ck_delivery_payout_batch_status"),
        CheckConstraint("amount_ugx > 0", name="ck_delivery_payout_batch_amount"),
        CheckConstraint("currency = 'UGX'", name="ck_delivery_payout_batch_currency"),
        UniqueConstraint("batch_reference", name="uq_delivery_payout_batch_reference"),
        UniqueConstraint("idempotency_key", name="uq_delivery_payout_batch_idempotency"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    agent_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("delivery_agents.user_id", ondelete="RESTRICT"), index=True)
    amount_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="UGX", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False, index=True)
    batch_reference: Mapped[str] = mapped_column(String(180), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    payout_reference: Mapped[str | None] = mapped_column(String(180), unique=True)
    authorized_by_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)


class DeliveryPayoutBatchLine(Base):
    """Exact rider earnings reserved by a payout batch."""
    __tablename__ = "delivery_payout_batch_lines"
    __table_args__ = (
        CheckConstraint("amount_ugx > 0", name="ck_delivery_payout_batch_line_amount"),
        CheckConstraint("currency = 'UGX'", name="ck_delivery_payout_batch_line_currency"),
        UniqueConstraint("batch_id", "assignment_id", name="uq_delivery_payout_batch_line_assignment"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("delivery_payout_batches.id", ondelete="CASCADE"), index=True)
    assignment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("delivery_earnings.assignment_id", ondelete="RESTRICT"), index=True)
    amount_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="UGX", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)


class DeliveryQuote(Base):
    """Committed delivery-pricing snapshot for one retailer fulfillment.

    Preserves the inputs and the result of the approved Phase 4A COM-FEE
    calculation so later pricing-configuration changes cannot silently change an
    already-created order, and so a committed fee can always be explained.
    """

    __tablename__ = "delivery_quotes"
    __table_args__ = (
        UniqueConstraint("fulfillment_id", name="uq_delivery_quote_fulfillment"),
        CheckConstraint("mode IN ('DELIVERY','PICKUP')", name="ck_delivery_quote_mode"),
        CheckConstraint(
            "(mode = 'DELIVERY' AND route_distance_km IS NOT NULL) OR "
            "(mode = 'PICKUP' AND route_distance_km IS NULL)",
            name="ck_delivery_quote_distance_matches_mode",
        ),
        CheckConstraint(
            "route_distance_km IS NULL OR route_distance_km >= 0",
            name="ck_delivery_quote_distance_nonnegative",
        ),
        CheckConstraint("delivery_fee_ugx >= 0", name="ck_delivery_quote_amount"),
        CheckConstraint(
            "base_fee_ugx >= 0 AND price_per_km_ugx >= 0 AND minimum_fee_ugx >= 0 "
            "AND rounding_increment_ugx > 0",
            name="ck_delivery_quote_pricing_parameters",
        ),
        CheckConstraint("currency = 'UGX'", name="ck_delivery_quote_currency"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    fulfillment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("retailer_fulfillments.id", ondelete="CASCADE")
    )
    retailer_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("retailers.id", ondelete="RESTRICT"), index=True
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    route_distance_km: Mapped[Decimal | None] = mapped_column(Numeric(9, 3))
    distance_source: Mapped[str | None] = mapped_column(String(40))
    base_fee_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    price_per_km_ugx: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    minimum_fee_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rounding_increment_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rounding_tie_break: Mapped[str] = mapped_column(String(8), nullable=False)
    pricing_version: Mapped[str] = mapped_column(String(60), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="UGX", nullable=False)
    delivery_fee_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount_ugx > 0 AND currency = 'UGX'", name="ck_payment_amount_currency"),
        CheckConstraint("status IN ('PENDING','UNKNOWN','SUCCESSFUL','FAILED','REFUNDED')", name="ck_payment_status"),
        CheckConstraint("method IN ('MTN_MOMO','AIRTEL_MONEY')", name="ck_payment_method_online_only"),
        UniqueConstraint("attempt_reference", name="uq_payment_attempt_reference"),
        UniqueConstraint("idempotency_key", name="uq_payment_idempotency_key"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
    customer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    amount_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="UGX", nullable=False)
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(180), unique=True)
    attempt_reference: Mapped[str] = mapped_column(
        String(180),
        default=lambda: f"attempt-{uuid4().hex}",
        nullable=False,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False, index=True)
    initiated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        CheckConstraint("status IN ('SUCCESSFUL','FAILED','REFUNDED')", name="ck_payment_event_status"),
        CheckConstraint("disposition IN ('APPLIED','IDEMPOTENT','CONFLICT')", name="ck_payment_event_disposition"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    payment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE"), index=True)
    provider_event_id: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    disposition: Mapped[str] = mapped_column(
        String(20),
        default="APPLIED",
        server_default=text("'APPLIED'"),
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PaymentReconciliation(Base):
    __tablename__ = "payment_reconciliations"
    __table_args__ = (
        CheckConstraint(
            "state IN ('REQUESTED','ATTEMPTED','UNRESOLVED','AUTHORITATIVE_SUCCESS',"
            "'AUTHORITATIVE_FAILURE','CONFLICT','MANUAL_REVIEW')",
            name="ck_payment_reconciliation_state",
        ),
        CheckConstraint("source IN ('SYSTEM','PROVIDER')", name="ck_payment_reconciliation_source"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    payment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("payments.id", ondelete="CASCADE"),
        index=True,
    )
    payment_event_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("payment_events.id", ondelete="SET NULL"),
        index=True,
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="SYSTEM", nullable=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        nullable=False,
    )
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentRefund(Base):
    __tablename__ = "payment_refunds"
    __table_args__ = (
        CheckConstraint("amount_ugx > 0", name="ck_payment_refund_amount"),
        CheckConstraint(
            "status IN ('SUBMITTED','UNKNOWN','CONFIRMED','FAILED')",
            name="ck_payment_refund_status",
        ),
        UniqueConstraint("idempotency_key", name="uq_payment_refund_idempotency_key"),
        UniqueConstraint("external_reference", name="uq_payment_refund_external_reference"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    payment_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("payments.id", ondelete="RESTRICT"),
        index=True,
    )
    amount_ugx: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="SUBMITTED", nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(180))
    external_reference: Mapped[str | None] = mapped_column(String(180))
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshTokenFamily(Base):
    __tablename__ = "refresh_token_families"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("refresh_token_families.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)


class VerificationToken(Base):
    __tablename__ = "verification_tokens"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    contact: Mapped[str] = mapped_column(String(320), nullable=False)
    purpose: Mapped[str] = mapped_column(String(12), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Review(TimestampMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("order_item_id", name="uq_review_order_item"),
                      CheckConstraint("rating BETWEEN 1 AND 5", name="ck_review_rating"),
                      CheckConstraint("moderation_status IN ('VISIBLE','HIDDEN')", name="ck_review_moderation_status"))
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    customer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    order_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("order_items.id", ondelete="RESTRICT"))
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str | None] = mapped_column(String(2000))
    moderation_status: Mapped[str] = mapped_column(String(20), default="VISIBLE", nullable=False)


class WishlistItem(Base):
    __tablename__ = "wishlist_items"
    __table_args__ = (UniqueConstraint("customer_id", "product_id", name="uq_wishlist_customer_product"),)
    customer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False)


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        Index("ix_notification_outbox_dispatch", "status", "available_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), default="IN_APP", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(1000))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlatformSetting(TimestampMixin, Base):
    __tablename__ = "platform_settings"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_by: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(80), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False, index=True)
