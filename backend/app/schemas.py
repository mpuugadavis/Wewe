from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import get_settings
from app.services.media_storage import MAX_PRODUCT_IMAGES, MediaValidationError, validate_product_image_url

Role = Literal["CUSTOMER", "RETAILER", "DELIVERY_AGENT", "ADMIN"]
PublicRole = Literal["CUSTOMER", "RETAILER", "DELIVERY_AGENT"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email: str | None = None
    phone: str | None = Field(default=None, min_length=8, max_length=20)
    password: str = Field(min_length=12, max_length=128)
    role: PublicRole = "CUSTOMER"
    business_name: str | None = Field(default=None, max_length=180)
    transport_mode: str | None = Field(default=None, max_length=40)

    @field_validator("email")
    @classmethod
    def validate_email_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            validated = validate_email(
                value.strip(),
                check_deliverability=False,
                test_environment=get_settings().app_env in {"development", "test"},
            )
        except EmailNotValidError as exc:
            raise ValueError("Enter a valid email address") from exc
        return validated.normalized

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is not None:
            cleaned = value.replace(" ", "").replace("-", "")
            if not cleaned.startswith("+") or not cleaned[1:].isdigit() or not 8 <= len(cleaned[1:]) <= 15:
                raise ValueError("Phone must use international format, for example +2567XXXXXXXX")
            return cleaned
        return None

    @model_validator(mode="after")
    def validate_contact_and_profile(self) -> "RegisterIn":
        if self.email is None and self.phone is None:
            raise ValueError("Provide an email address or phone number")
        if self.role == "RETAILER" and not self.business_name:
            raise ValueError("business_name is required for retailer registration")
        if self.role == "RETAILER" and not self.phone:
            raise ValueError("phone is required for retailer registration")
        if self.role == "DELIVERY_AGENT" and not self.phone:
            raise ValueError("phone is required for delivery-agent registration")
        return self


class LoginIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=256)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(ORMModel):
    id: UUID
    name: str
    email: str | None
    phone: str | None
    role: Role
    status: str
    email_verified_at: Any | None = None
    phone_verified_at: Any | None = None


class ResetRequestIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)


class ResetConfirmIn(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    new_password: str = Field(min_length=12, max_length=128)


class VerificationRequestIn(BaseModel):
    purpose: Literal["EMAIL", "PHONE"]


class VerificationConfirmIn(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class CategoryOut(ORMModel):
    id: UUID
    parent_id: UUID | None
    name: str
    slug: str
    is_active: bool
    sort_order: int


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    parent_id: UUID | None = None
    sort_order: int = Field(default=0, ge=0)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=220)
    description: str | None = Field(default=None, max_length=10000)
    category_id: UUID
    sku: str | None = Field(default=None, max_length=100)
    price_ugx: int = Field(gt=0, le=2_000_000_000)
    stock_quantity: int = Field(ge=0, le=2_000_000)
    image_urls: list[str] = Field(default_factory=list, max_length=MAX_PRODUCT_IMAGES)

    @field_validator("image_urls")
    @classmethod
    def validate_image_urls(cls, values: list[str]) -> list[str]:
        allowed_hosts = {
            host.strip().lower()
            for host in get_settings().media_allowed_hosts.split(",")
            if host.strip()
        }
        normalized: list[str] = []
        for value in values:
            try:
                normalized.append(validate_product_image_url(value, allowed_hosts=allowed_hosts or None))
            except MediaValidationError as exc:
                raise ValueError(str(exc)) from exc
        if len({value.lower() for value in normalized}) != len(normalized):
            raise ValueError("Duplicate product image URLs are not allowed.")
        return normalized


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=220)
    description: str | None = Field(default=None, max_length=10000)
    category_id: UUID | None = None
    sku: str | None = Field(default=None, max_length=100)
    price_ugx: int | None = Field(default=None, gt=0, le=2_000_000_000)
    stock_quantity: int | None = Field(default=None, ge=0, le=2_000_000)
    is_active: bool | None = None


class ProductImageReorder(BaseModel):
    image_ids: list[UUID] = Field(min_length=1, max_length=MAX_PRODUCT_IMAGES)

    @field_validator("image_ids")
    @classmethod
    def validate_unique_image_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Image IDs must be unique.")
        return value


class ProductModerationUpdate(BaseModel):
    status: Literal["ACTIVE", "INACTIVE", "REMOVED"]


class ProductOut(BaseModel):
    id: UUID
    category_id: UUID
    name: str
    description: str | None
    images: list[str]
    listings: list[dict[str, Any]]


class CartItemIn(BaseModel):
    retailer_product_id: UUID
    quantity: int = Field(gt=0, le=100)


class CartItemUpdate(BaseModel):
    quantity: int = Field(gt=0, le=100)


class CheckoutIn(BaseModel):
    delivery_method: Literal["DELIVERY", "PICKUP"]
    delivery_point_id: UUID | None = None
    pickup_point_id: UUID | None = None
    # A road-route distance is never accepted from the client: WEWE obtains it
    # from the routing service for the actual route between the retailer pickup
    # location and the delivery point (COM-FEE-004), so no caller-supplied or
    # hard-coded distance can reach the pricing engine.

    @model_validator(mode="after")
    def validate_delivery_choice(self) -> "CheckoutIn":
        if self.delivery_method == "DELIVERY" and self.delivery_point_id is None:
            raise ValueError("delivery_point_id is required for delivery")
        if self.delivery_method == "PICKUP" and self.pickup_point_id is None:
            raise ValueError("pickup_point_id is required for pickup")
        return self


class OrderOut(BaseModel):
    id: UUID
    order_number: str
    customer_id: UUID
    delivery_point_id: UUID | None
    pickup_point_id: UUID | None
    delivery_method: str
    currency: str
    subtotal_ugx: int
    delivery_fee_ugx: int
    total_ugx: int
    status: str
    payment_status: str
    created_at: Any
    items: list[dict[str, Any]]
    deliveries: list[dict[str, Any]] = Field(default_factory=list)
    delivery_quotes: list[dict[str, Any]] = Field(default_factory=list)


class PaymentCreate(BaseModel):
    """Online payment only: WEWE is online-payment-only and cash is out of scope (COM-PAY-004 / COM-MULTI-001)."""

    method: Literal["MTN_MOMO", "AIRTEL_MONEY"]
    phone: str = Field(min_length=9, max_length=16)

    @model_validator(mode="after")
    def require_mobile_number(self) -> "PaymentCreate":
        if not self.phone.startswith("+") or not self.phone[1:].isdigit():
            raise ValueError("A phone number in international format is required for mobile money")
        return self


class PaymentOut(ORMModel):
    id: UUID
    order_id: UUID
    amount_ugx: int
    currency: str
    method: str
    provider: str
    provider_reference: str | None
    status: str
    attempt_reference: str
    created_at: Any
    initiated_at: Any | None = None
    resolved_at: Any | None = None
    checkout_url: str | None = None
    idempotent_replay: bool = False


class PaymentWebhookIn(BaseModel):
    provider_reference: str = Field(min_length=4, max_length=180)
    provider_event_id: str = Field(min_length=4, max_length=180)
    amount_ugx: int = Field(gt=0)
    currency: Literal["UGX"]
    status: Literal["SUCCESSFUL", "FAILED", "REFUNDED"]


class ReviewCreate(BaseModel):
    order_item_id: UUID
    rating: int = Field(ge=1, le=5)
    body: str | None = Field(default=None, max_length=2000)


class WishlistIn(BaseModel):
    product_id: UUID


class DeliveryStatusUpdate(BaseModel):
    status: Literal["PICKED_UP", "OUT_FOR_DELIVERY", "DELIVERED"]
    confirmation_code: str | None = Field(default=None, min_length=4, max_length=12)


class AvailabilityUpdate(BaseModel):
    availability_status: Literal["AVAILABLE", "OFFLINE"]


class DeliveryAgentLocationUpdate(BaseModel):
    latitude: Decimal = Field(ge=-90, le=90)
    longitude: Decimal = Field(ge=-180, le=180)
    accuracy_m: Decimal = Field(ge=0, le=100000)
    heading_deg: Decimal | None = Field(default=None, ge=0, lt=360)
    speed_mps: Decimal | None = Field(default=None, ge=0, le=1000)


class DeliveryAgentLocationOut(BaseModel):
    agent_id: UUID
    latitude: float
    longitude: float
    accuracy_m: float
    heading_deg: float | None = None
    speed_mps: float | None = None
    updated_at: datetime



class FulfillmentAction(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class UserStatusUpdate(BaseModel):
    status: Literal["ACTIVE", "SUSPENDED", "DEACTIVATED"]


class CustomerProfileUpdate(BaseModel):
    preferred_delivery_point_id: UUID | None = None
    marketing_opt_in: bool | None = None


class RetailerProfileUpdate(BaseModel):
    business_name: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=3000)
    phone: str | None = Field(default=None, min_length=8, max_length=20)
    location_id: UUID | None = None

    @model_validator(mode="after")
    def require_changes(self) -> "RetailerProfileUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide at least one profile field to update")
        if "business_name" in self.model_fields_set and self.business_name is None:
            raise ValueError("business_name cannot be cleared")
        if "phone" in self.model_fields_set and self.phone is None:
            raise ValueError("phone cannot be cleared")
        return self


class RetailerAvailabilityUpdate(BaseModel):
    is_open: bool


class DeliveryAgentProfileUpdate(BaseModel):
    phone: str | None = Field(default=None, min_length=8, max_length=20)
    transport_mode: str | None = Field(default=None, max_length=40)


class UniversityCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    slug: str = Field(min_length=2, max_length=180, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    country_code: str = Field(default="UG", min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")


class CampusCreate(BaseModel):
    university_id: UUID
    name: str = Field(min_length=2, max_length=180)
    slug: str = Field(min_length=2, max_length=180, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class HallCreate(BaseModel):
    campus_id: UUID
    name: str = Field(min_length=2, max_length=180)
    kind: Literal["HALL", "HOSTEL"] = "HALL"


class BlockCreate(BaseModel):
    hall_id: UUID
    name: str = Field(min_length=1, max_length=100)


class PickupPointCreate(BaseModel):
    campus_id: UUID
    hall_id: UUID | None = None
    name: str = Field(min_length=2, max_length=180)
    directions: str | None = Field(default=None, max_length=500)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    contact_name: str | None = Field(default=None, max_length=120)
    contact_phone: str | None = Field(default=None, min_length=8, max_length=20)
    opening_hours: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_coordinate_pair(self) -> "PickupPointCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Provide both latitude and longitude, or neither")
        return self


class PickupPointStatusUpdate(BaseModel):
    operating_status: Literal["OPEN", "CLOSED", "TEMPORARILY_UNAVAILABLE"]


class AdminDeliveryAssignment(BaseModel):
    agent_user_id: UUID


class DeliveryPayoutIn(BaseModel):
    payout_reference: str = Field(min_length=4, max_length=180)


class RefundConfirmationIn(BaseModel):
    provider_event_id: str = Field(min_length=4, max_length=180)


class ReviewModerationUpdate(BaseModel):
    status: Literal["VISIBLE", "HIDDEN"]


class AdminOrderStatusUpdate(BaseModel):
    status: Literal["CANCELLED", "FAILED"]
    reason: str = Field(min_length=3, max_length=300)


class RetailerVerificationUpdate(BaseModel):
    status: Literal["VERIFIED", "REJECTED"]
    reason: str | None = Field(default=None, max_length=300)


class SettlementCreate(BaseModel):
    retailer_id: UUID
    amount_ugx: int = Field(gt=0, le=2_000_000_000)
    settlement_reference: str = Field(min_length=4, max_length=180)
    idempotency_key: str = Field(min_length=4, max_length=180)


class SettlementPayoutUpdate(BaseModel):
    payout_reference: str = Field(min_length=4, max_length=180)


class SettlementOut(ORMModel):
    id: UUID
    retailer_id: UUID
    amount_ugx: int
    currency: str
    status: Literal["DRAFT", "SUBMITTED", "SETTLED", "FAILED", "REVIEW_REQUIRED"]
    settlement_reference: str
    idempotency_key: str
    payout_reference: str | None
    authorized_by_user_id: UUID | None
    submitted_at: Any | None
    settled_at: Any | None
    line_count: int
    line_total_ugx: int
    is_balanced: bool


class LocationCreate(BaseModel):
    campus_id: UUID
    hall_id: UUID | None = None
    block_id: UUID | None = None
    kind: Literal["ROOM", "PICKUP_POINT", "BUILDING", "OTHER"]
    name: str = Field(min_length=2, max_length=180)
    directions: str | None = Field(default=None, max_length=500)
    #: Optional WGS84 coordinates. They are the routing service's origin or
    #: destination, never a distance: WEWE always asks a routing provider for
    #: the road route (COM-FEE-004).
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    google_place_id: str | None = Field(default=None, max_length=300)
    is_private: bool = False

    @model_validator(mode="after")
    def require_coordinate_pair(self) -> "LocationCreate":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Provide both latitude and longitude, or neither")
        return self


class LocationOut(ORMModel):
    id: UUID
    campus_id: UUID
    hall_id: UUID | None
    block_id: UUID | None
    kind: str
    name: str
    directions: str | None
    latitude: float | None = None
    longitude: float | None = None
    google_place_id: str | None = None
    is_private: bool
    is_active: bool


class AdminSettingUpdate(BaseModel):
    value: dict[str, Any]
