from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Order, PlatformSetting
from app.services.platform_economics import (
    DEFAULT_PLATFORM_COMMISSION_PERCENT,
    calculate_commission_ugx,
    resolve_platform_commission_config,
    snapshot_order_commission,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _order(subtotal=25_000):
    customer_id = uuid4()
    return Order(
        id=uuid4(),
        order_number=f"ORD-{uuid4().hex[:8]}",
        customer_id=customer_id,
        delivery_point_id=uuid4(),
        delivery_method="DELIVERY",
        currency="UGX",
        subtotal_ugx=subtotal,
        gross_delivery_fee_ugx=2_500,
        multi_retailer_discount_ugx=0,
        multi_retailer_discount_percent=0,
        delivery_fee_ugx=2_500,
        total_ugx=subtotal + 2_500,
    )


def test_default_commission_is_eight_percent():
    assert DEFAULT_PLATFORM_COMMISSION_PERCENT == Decimal("8")
    assert calculate_commission_ugx(10_000, Decimal("8")) == 800
    assert calculate_commission_ugx(25_000, Decimal("8")) == 2_000
    assert calculate_commission_ugx(50_000, Decimal("8")) == 4_000


def test_admin_setting_overrides_default_and_is_snapshotted():
    with _session() as session:
        session.add(PlatformSetting(key="platform_commission", value={"percent": "10"}))
        session.commit()

        order = _order(25_000)
        snapshot_order_commission(session, order)
        assert order.platform_commission_percent == Decimal("10")
        assert order.platform_commission_ugx == 2_500


def test_commission_snapshot_does_not_change_when_setting_changes():
    with _session() as session:
        session.add(PlatformSetting(key="platform_commission", value={"percent": "8"}))
        session.commit()
        order = _order(25_000)
        snapshot_order_commission(session, order)
        session.get(PlatformSetting, "platform_commission").value = {"percent": "12"}
        session.commit()
        assert order.platform_commission_percent == Decimal("8")
        assert order.platform_commission_ugx == 2_000
