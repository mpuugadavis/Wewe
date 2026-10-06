"""Provider-neutral delivery pricing for WEWE retailer fulfillments.

Implements the approved Phase 4A COM-FEE rules (Phase 4B.3):

    raw_delivery_fee = max(minimum_fee, base_fee + (route_distance_km x price_per_km))
    delivery_fee     = raw_delivery_fee rounded to the nearest configured UGX increment

For orders containing multiple retailer fulfillments, the individual fees are
still calculated and snapshotted, then one configurable consolidation discount
is applied to the combined gross delivery fee.

Design boundaries:

* Road-route distance is an **input**. This module never calls Google Maps,
  Mapbox, OpenStreetMap routing, or any other network service, and it never
  derives a "road distance" from straight-line/Haversine coordinates. Those
  lookups live in :mod:`app.services.routing`, which supplies the distance and
  the ``distance_source`` recorded on every quote.
* Every fulfillment is priced independently (COM-FEE-002), preserving each
  retailer's route and fee as an auditable quote. Multi-retailer orders then
  receive one configurable consolidation discount at order level.
* Pickup pricing is UGX 0 (COM-FEE-003) with no route distance.
* Pricing parameters are configuration, not permanent constants
  (COM-FEE-008). ``APPROVED_DELIVERY_PRICING_CONFIG`` holds the values approved
  in ``docs/WEWE_COMMERCE_BUSINESS_RULES_PHASE_4A.md`` and an explicit
  ``platform_settings`` row can override them.
* An uncertain route is refused, never guessed (COM-FEE-009): a distance beyond
  the configured normal maximum or beyond the supported precision raises
  :class:`DeliveryPricingError` instead of inventing a price.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DeliveryQuote, PlatformSetting, RetailerFulfillment, utcnow

DELIVERY: Literal["DELIVERY"] = "DELIVERY"
PICKUP: Literal["PICKUP"] = "PICKUP"
DeliveryMode = Literal["DELIVERY", "PICKUP"]

#: ``platform_settings`` key holding an explicit delivery-pricing configuration.
PRICING_SETTING_KEY = "delivery_pricing"

#: Fallback source label for direct pricing-engine callers that already supplied a road route.
SUPPLIED_ROAD_ROUTE = "SUPPLIED_ROAD_ROUTE"

#: Version label for the approved Phase 4A COM-FEE-001/COM-FEE-008 parameters.
APPROVED_PRICING_VERSION = "phase4a-com-fee-001"

#: Road-route distances are stored with millimetre precision; more precision is
#: refused rather than silently truncated.
ROUTE_DISTANCE_DECIMALS = 3

_TIE_BREAK_ROUNDING = {
    "UP": ROUND_HALF_UP,
    "DOWN": ROUND_HALF_DOWN,
    "EVEN": ROUND_HALF_EVEN,
}

_CONFIG_FIELDS = (
    "base_fee_ugx",
    "price_per_km_ugx",
    "minimum_fee_ugx",
    "rounding_increment_ugx",
    "max_route_distance_km",
    "rounding_tie_break",
    "version",
    "multi_retailer_discount_percent",
)


class DeliveryPricingError(ValueError):
    """Raised when delivery pricing cannot be produced from the given inputs."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _as_amount(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DeliveryPricingError(
            "invalid_pricing_configuration",
            f"{field} must be a non-negative whole UGX amount.",
        )
    return value


def _as_decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise DeliveryPricingError("invalid_pricing_configuration", f"{field} must be a number.")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, str | float):
        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            raise DeliveryPricingError(
                "invalid_pricing_configuration", f"{field} must be a number."
            ) from None
    else:
        raise DeliveryPricingError("invalid_pricing_configuration", f"{field} must be a number.")
    if not amount.is_finite():
        raise DeliveryPricingError("invalid_pricing_configuration", f"{field} must be finite.")
    return amount


@dataclass(frozen=True)
class DeliveryPricingConfig:
    """Immutable delivery-pricing configuration (COM-FEE-008)."""

    base_fee_ugx: int
    price_per_km_ugx: Decimal
    minimum_fee_ugx: int
    rounding_increment_ugx: int
    max_route_distance_km: Decimal
    rounding_tie_break: str = "UP"
    currency: str = "UGX"
    version: str = APPROVED_PRICING_VERSION
    multi_retailer_discount_percent: Decimal = Decimal("15")

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_fee_ugx", _as_amount(self.base_fee_ugx, "base_fee_ugx"))
        object.__setattr__(
            self, "minimum_fee_ugx", _as_amount(self.minimum_fee_ugx, "minimum_fee_ugx")
        )
        price_per_km = _as_decimal(self.price_per_km_ugx, "price_per_km_ugx")
        if price_per_km < 0:
            raise DeliveryPricingError(
                "invalid_pricing_configuration", "price_per_km_ugx must not be negative."
            )
        object.__setattr__(self, "price_per_km_ugx", price_per_km)
        increment = self.rounding_increment_ugx
        if isinstance(increment, bool) or not isinstance(increment, int) or increment <= 0:
            raise DeliveryPricingError(
                "invalid_pricing_configuration", "rounding_increment_ugx must be a positive integer."
            )
        max_distance = _as_decimal(self.max_route_distance_km, "max_route_distance_km")
        if max_distance <= 0:
            raise DeliveryPricingError(
                "invalid_pricing_configuration", "max_route_distance_km must be greater than zero."
            )
        object.__setattr__(self, "max_route_distance_km", max_distance)
        if self.rounding_tie_break not in _TIE_BREAK_ROUNDING:
            raise DeliveryPricingError(
                "invalid_pricing_configuration",
                "rounding_tie_break must be one of UP, DOWN or EVEN.",
            )
        discount_percent = _as_decimal(self.multi_retailer_discount_percent, "multi_retailer_discount_percent")
        if discount_percent < 0 or discount_percent > 100:
            raise DeliveryPricingError("invalid_pricing_configuration", "multi_retailer_discount_percent must be between 0 and 100.")
        object.__setattr__(self, "multi_retailer_discount_percent", discount_percent)
        if self.currency != "UGX":
            raise DeliveryPricingError(
                "invalid_pricing_configuration", "Delivery pricing currently supports UGX only."
            )
        if not isinstance(self.version, str) or not self.version or len(self.version) > 60:
            raise DeliveryPricingError(
                "invalid_pricing_configuration", "version must be a non-empty string of at most 60 characters."
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DeliveryPricingConfig":
        """Build a configuration from a ``platform_settings`` JSON value."""

        if not isinstance(value, Mapping):
            raise DeliveryPricingError(
                "invalid_pricing_configuration", "Delivery pricing configuration must be an object."
            )
        unknown = set(value) - set(_CONFIG_FIELDS)
        if unknown:
            raise DeliveryPricingError(
                "invalid_pricing_configuration",
                f"Unknown delivery pricing configuration fields: {', '.join(sorted(unknown))}.",
            )
        required_fields = [
            field for field in _CONFIG_FIELDS if field not in {"version", "rounding_tie_break"}
        ]
        missing = sorted(field for field in required_fields if field not in value)
        if missing:
            raise DeliveryPricingError(
                "invalid_pricing_configuration",
                f"Delivery pricing configuration is incomplete: {', '.join(missing)}.",
            )
        version = value.get("version") or f"platform-setting:{PRICING_SETTING_KEY}"
        return cls(
            base_fee_ugx=value["base_fee_ugx"],
            price_per_km_ugx=value["price_per_km_ugx"],
            minimum_fee_ugx=value["minimum_fee_ugx"],
            rounding_increment_ugx=value["rounding_increment_ugx"],
            max_route_distance_km=value["max_route_distance_km"],
            rounding_tie_break=value.get("rounding_tie_break", "UP"),
            version=version,
            multi_retailer_discount_percent=value.get("multi_retailer_discount_percent", 15),
        )

    def delivery_fee(self, route_distance_km: Decimal | int | str | float) -> int:
        """Price a supplied ROAD-ROUTE distance in kilometres (COM-FEE-001)."""

        distance = _as_route_distance(route_distance_km, self.max_route_distance_km)
        raw_fee = self.base_fee_ugx + (distance * self.price_per_km_ugx)
        if raw_fee < self.minimum_fee_ugx:
            raw_fee = Decimal(self.minimum_fee_ugx)
        return _round_to_increment(raw_fee, self.rounding_increment_ugx, self.rounding_tie_break)


def _as_route_distance(value: Any, max_distance_km: Decimal) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise DeliveryPricingError(
            "invalid_route_distance", "A road-route distance in kilometres is required."
        )
    if isinstance(value, Decimal):
        distance = value
    elif isinstance(value, int):
        distance = Decimal(value)
    elif isinstance(value, str | float):
        try:
            distance = Decimal(str(value))
        except InvalidOperation:
            raise DeliveryPricingError(
                "invalid_route_distance", "Road-route distance must be a number of kilometres."
            ) from None
    else:
        raise DeliveryPricingError(
            "invalid_route_distance", "Road-route distance must be a number of kilometres."
        )
    if not distance.is_finite() or distance < 0:
        raise DeliveryPricingError(
            "invalid_route_distance", "Road-route distance must not be negative."
        )
    if -distance.as_tuple().exponent > ROUTE_DISTANCE_DECIMALS:
        raise DeliveryPricingError(
            "route_distance_precision_unsupported",
            f"Road-route distance supports at most {ROUTE_DISTANCE_DECIMALS} decimal places.",
        )
    if distance > max_distance_km:
        raise DeliveryPricingError(
            "route_distance_exceeds_maximum",
            "The road-route distance exceeds the configured normal maximum, which requires an "
            "explicit business quote.",
        )
    return distance


def _round_to_increment(value: Decimal, increment_ugx: int, tie_break: str) -> int:
    steps = value / Decimal(increment_ugx)
    rounded = steps.quantize(Decimal(1), rounding=_TIE_BREAK_ROUNDING[tie_break])
    return int(rounded) * increment_ugx


#: Approved initial Phase 4A configuration (COM-FEE-001 / COM-FEE-008).
#: These are configuration values, not permanent constants: an explicit
#: ``platform_settings`` row (``PRICING_SETTING_KEY``) overrides them.
APPROVED_DELIVERY_PRICING_CONFIG = DeliveryPricingConfig(
    base_fee_ugx=1_500,
    price_per_km_ugx=Decimal("500"),
    minimum_fee_ugx=2_500,
    rounding_increment_ugx=500,
    max_route_distance_km=Decimal("15"),
)


@dataclass(frozen=True)
class DeliveryPriceQuote:
    """A calculated, explainable delivery price for one retailer fulfillment."""

    retailer_id: UUID
    mode: DeliveryMode
    route_distance_km: Decimal | None
    distance_source: str | None
    delivery_fee_ugx: int
    currency: str
    base_fee_ugx: int
    price_per_km_ugx: Decimal
    minimum_fee_ugx: int
    rounding_increment_ugx: int
    rounding_tie_break: str
    pricing_version: str
    quoted_at: datetime


def build_delivery_quote(
    config: DeliveryPricingConfig,
    *,
    retailer_id: UUID,
    mode: DeliveryMode,
    route_distance_km: Decimal | int | str | float | None = None,
    distance_source: str | None = None,
    quoted_at: datetime | None = None,
) -> DeliveryPriceQuote:
    """Price one retailer fulfillment from inputs that are already available."""

    if mode not in (DELIVERY, PICKUP):
        raise DeliveryPricingError(
            "invalid_delivery_mode", "Delivery mode must be DELIVERY or PICKUP."
        )
    if mode == PICKUP:
        if route_distance_km is not None:
            raise DeliveryPricingError(
                "unexpected_route_distance", "A pickup fulfillment has no delivery route distance."
            )
        distance: Decimal | None = None
        source: str | None = None
        fee = 0
    else:
        if route_distance_km is None:
            raise DeliveryPricingError(
                "route_distance_required", "A delivery fulfillment requires a road-route distance."
            )
        distance = _as_route_distance(route_distance_km, config.max_route_distance_km)
        source = distance_source or SUPPLIED_ROAD_ROUTE
        if len(source) > 40:
            raise DeliveryPricingError(
                "invalid_route_distance",
                "distance_source must be at most 40 characters.",
            )
        fee = config.delivery_fee(distance)
    return DeliveryPriceQuote(
        retailer_id=retailer_id,
        mode=mode,
        route_distance_km=distance,
        distance_source=source,
        delivery_fee_ugx=fee,
        currency=config.currency,
        base_fee_ugx=config.base_fee_ugx,
        price_per_km_ugx=config.price_per_km_ugx,
        minimum_fee_ugx=config.minimum_fee_ugx,
        rounding_increment_ugx=config.rounding_increment_ugx,
        rounding_tie_break=config.rounding_tie_break,
        pricing_version=config.version,
        quoted_at=quoted_at or utcnow(),
    )


@dataclass(frozen=True)
class MultiRetailerDeliveryTotal:
    """Order-level delivery total after one consolidation discount."""
    gross_delivery_fee_ugx: int
    multi_retailer_discount_ugx: int
    delivery_fee_ugx: int
    retailer_count: int
    discount_percent: Decimal


def calculate_multi_retailer_delivery_total(
    quotes: Iterable[DeliveryPriceQuote], config: DeliveryPricingConfig
) -> MultiRetailerDeliveryTotal:
    """Combine retailer fees and apply one order-level consolidation discount."""
    quote_list = list(quotes)
    gross = sum(quote.delivery_fee_ugx for quote in quote_list)
    retailer_count = len(quote_list)
    discount = 0
    if retailer_count >= 2 and gross > 0 and config.multi_retailer_discount_percent > 0:
        discount = int((Decimal(gross) * config.multi_retailer_discount_percent / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return MultiRetailerDeliveryTotal(
        gross_delivery_fee_ugx=gross,
        multi_retailer_discount_ugx=discount,
        delivery_fee_ugx=gross - discount,
        retailer_count=retailer_count,
        discount_percent=(config.multi_retailer_discount_percent if retailer_count >= 2 else Decimal("0")),
    )


def total_delivery_fee(quotes: Iterable[DeliveryPriceQuote]) -> int:
    """Backward-compatible sum of independent fulfillment fees."""
    return sum(quote.delivery_fee_ugx for quote in quotes)



def resolve_delivery_pricing_config(db: Session) -> DeliveryPricingConfig:
    """Return the configured delivery-pricing parameters.

    The approved Phase 4A values apply until an explicit ``platform_settings``
    row supplies a different configuration. Raises :class:`DeliveryPricingError`
    for an invalid configuration so checkout can refuse rather than guess.
    """

    setting = db.get(PlatformSetting, PRICING_SETTING_KEY)
    if setting is None:
        return APPROVED_DELIVERY_PRICING_CONFIG
    return DeliveryPricingConfig.from_mapping(setting.value)


def commit_delivery_quote(
    db: Session, quote: DeliveryPriceQuote, *, fulfillment_id: UUID
) -> DeliveryQuote:
    """Persist a computed quote as an immutable-per-order snapshot."""

    row = DeliveryQuote(
        fulfillment_id=fulfillment_id,
        retailer_id=quote.retailer_id,
        mode=quote.mode,
        route_distance_km=quote.route_distance_km,
        distance_source=quote.distance_source,
        base_fee_ugx=quote.base_fee_ugx,
        price_per_km_ugx=quote.price_per_km_ugx,
        minimum_fee_ugx=quote.minimum_fee_ugx,
        rounding_increment_ugx=quote.rounding_increment_ugx,
        rounding_tie_break=quote.rounding_tie_break,
        pricing_version=quote.pricing_version,
        currency=quote.currency,
        delivery_fee_ugx=quote.delivery_fee_ugx,
        quoted_at=quote.quoted_at,
    )
    db.add(row)
    db.flush()
    return row


def remove_committed_delivery_quote(db: Session, fulfillment_id: UUID) -> int | None:
    """Release one fulfillment's committed fee, keeping the snapshot for audit.

    Returns the removed fee, or ``None`` when the fulfillment has no committed
    quote (a pre-Phase-4B.3 order).
    """

    quote = db.scalar(
        select(DeliveryQuote)
        .where(DeliveryQuote.fulfillment_id == fulfillment_id, DeliveryQuote.removed_at.is_(None))
        .with_for_update()
    )
    if quote is None:
        return None
    # No mid-transaction flush: the caller may be part-way through updating the
    # order amounts, and the database checks the order arithmetic on flush.
    quote.removed_at = utcnow()
    return quote.delivery_fee_ugx


def committed_quotes_for_order(db: Session, order_id: UUID) -> list[DeliveryQuote]:
    """Return every committed quote snapshot for an order, in creation order."""

    return list(
        db.scalars(
            select(DeliveryQuote)
            .join(RetailerFulfillment, RetailerFulfillment.id == DeliveryQuote.fulfillment_id)
            .where(RetailerFulfillment.order_id == order_id)
            .order_by(DeliveryQuote.quoted_at, DeliveryQuote.id)
        ).all()
    )

    return amount
