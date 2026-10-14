from uuid import uuid4
import pytest
from sqlalchemy import select
from app.dependencies import Principal
from app.models import User, Retailer, DeliveryAgent, NotificationOutbox
from app.routers.admin import verify_retailer, verify_delivery_agent
from app.schemas import RetailerVerificationUpdate
from test_delivery_dispatch import _dispatch_fixture, _user


@pytest.mark.parametrize("role", ["RETAILER", "RIDER"])
def test_verification_notifies_both_channels_once(database, role):
    _, rider, _ = _dispatch_fixture(database)
    admin = _user("ADMIN", "Admin")
    database.add(admin)
    database.flush()
    principal = Principal(admin, uuid4())
    if role == "RETAILER":
        target = database.scalar(select(Retailer))
        target.verification_status = "PENDING"
        user_id = target.user_id
        call = lambda: verify_retailer(target.id, RetailerVerificationUpdate(status="VERIFIED"), principal=principal, db=database)
    else:
        target = database.get(DeliveryAgent, rider.id)
        target.verification_status = "PENDING"
        user_id = rider.id
        call = lambda: verify_delivery_agent(rider.id, RetailerVerificationUpdate(status="VERIFIED"), principal=principal, db=database)
    database.commit()
    call()
    call()
    rows = database.scalars(select(NotificationOutbox).where(NotificationOutbox.user_id == user_id)).all()
    assert len(rows) == 2
    assert {row.channel for row in rows} == {"EMAIL", "IN_APP"}
    assert all("verified" in row.payload["message"] for row in rows)
    email = next(row for row in rows if row.channel == "EMAIL")
    assert email.payload["to"] == database.get(User, user_id).email
    assert email.payload["body"] == email.payload["message"]
