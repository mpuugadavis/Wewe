from datetime import datetime
import pytest
from sqlalchemy import text
from app.models import PlatformSetting, User, AuditLog, WishlistItem, NotificationOutbox, PaymentEvent

def test_models_have_server_default():
    # Mixin models
    assert User.__table__.c.created_at.server_default is not None
    assert User.__table__.c.updated_at.server_default is not None

    # Inline created_at models
    assert AuditLog.__table__.c.created_at.server_default is not None
    assert WishlistItem.__table__.c.created_at.server_default is not None

    # Unrelated date/time columns must not have server_default
    assert NotificationOutbox.__table__.c.available_at.server_default is None
    assert PaymentEvent.__table__.c.received_at.server_default is None

def test_raw_sql_insert_uses_db_default_timestamps(database):
    # Verify that inserting a row without explicit timestamps relies on DB defaults
    # In SQLite/Postgres test environments with create_all, server_default is populated.
    setting_key = "test_timestamp_default_key"
    database.execute(
        text(
            """
            INSERT INTO platform_settings (key, value)
            VALUES (:key, :value)
            """
        ),
        {
            "key": setting_key,
            "value": '{"enabled": true}',
        },
    )
    database.commit()

    setting = database.get(PlatformSetting, setting_key)
    assert setting is not None
    assert isinstance(setting.created_at, datetime)
    assert isinstance(setting.updated_at, datetime)




