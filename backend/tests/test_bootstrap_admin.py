import pytest
from app.bootstrap_admin import create_first_admin
from app.security import verify_password


def test_bootstrap_requires_strong_password_and_refuses_second_admin(database):
    with pytest.raises(ValueError, match="16 characters"):
        create_first_admin(database, "owner@example.com", "Owner", "short")
    user = create_first_admin(database, "owner@example.com", "Owner", "a-long-private-test-password")
    assert user.role == "ADMIN"
    assert verify_password("a-long-private-test-password", user.password_hash)
    with pytest.raises(ValueError, match="already exists"):
        create_first_admin(database, "another@example.com", "Another", "another-long-private-password")
