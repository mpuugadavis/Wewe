"""WEWE marketplace economics rules.

The initial commercial model keeps delivery pricing separate from marketplace
revenue: riders earn the committed delivery fee, while WEWE earns a configurable
commission on merchandise sales. Commission is snapshotted on the order so later
admin changes cannot mutate existing orders.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, PlatformSetting

COMMISSION_SETTING_KEY = "platform_commission"
DEFAULT_PLATFORM_COMMISSION_PERCENT = Decimal("8")
MAX_PLATFORM_COMMISSION_PERCENT = Decimal("30")


class PlatformEconomicsError(ValueError):
    pass


@dataclass(frozen=True)
class PlatformCommissionConfig:
    percent: Decimal = DEFAULT_PLATFORM_COMMISSION_PERCENT

    def __post_init__(self) -> None:
        value = Decimal(str(self.percent))
        if value < 0 or value > MAX_PLATFORM_COMMISSION_PERCENT:
            raise PlatformEconomicsError("Platform commission must be between 0% and 30%.")
        object.__setattr__(self, "percent", value)


def resolve_platform_commission_config(db: Session) -> PlatformCommissionConfig:
    setting = db.get(PlatformSetting, COMMISSION_SETTING_KEY)
    if setting is None:
        return PlatformCommissionConfig()
    value: Any = setting.value.get("percent") if isinstance(setting.value, dict) else None
    if value is None:
        raise PlatformEconomicsError("Platform commission setting is incomplete.")
    try:
        return PlatformCommissionConfig(Decimal(str(value)))
    except (ValueError, TypeError):
        raise PlatformEconomicsError("Platform commission setting is invalid.") from None


def calculate_commission_ugx(merchandise_ugx: int, percent: Decimal) -> int:
    if merchandise_ugx < 0:
        raise PlatformEconomicsError("Merchandise amount cannot be negative.")
    rate = PlatformCommissionConfig(percent).percent
    return int((Decimal(merchandise_ugx) * rate / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def retailer_payable_ugx(merchandise_ugx: int, commission_ugx: int) -> int:
    if merchandise_ugx < 0 or commission_ugx < 0 or commission_ugx > merchandise_ugx:
        raise PlatformEconomicsError("Invalid retailer payable calculation.")
    return merchandise_ugx - commission_ugx


def snapshot_order_commission(db: Session, order: Order) -> None:
    config = resolve_platform_commission_config(db)
    order.platform_commission_percent = config.percent
    order.platform_commission_ugx = calculate_commission_ugx(order.subtotal_ugx, config.percent)
