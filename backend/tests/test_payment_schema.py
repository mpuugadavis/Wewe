from pydantic import ValidationError
import pytest

from app.schemas import PaymentCreate


@pytest.mark.parametrize(
    ("phone", "expected"),
    [
        ("0700000000", "+256700000000"),
        ("256700000000", "+256700000000"),
        ("00256700000000", "+256700000000"),
        ("+256700000000", "+256700000000"),
        ("+256 (700) 000-000", "+256700000000"),
        ("0700 000 000", "+256700000000"),
    ],
)
def test_payment_phone_normalizes_common_uganda_formats(phone, expected):
    payload = PaymentCreate(method="MTN_MOMO", phone=phone, email="customer@example.com")
    assert payload.phone == expected


def test_payment_phone_rejects_non_uganda_number():
    with pytest.raises(ValidationError):
        PaymentCreate(method="MTN_MOMO", phone="+254700000000", email="customer@example.com")


def test_payment_phone_rejects_malformed_number():
    with pytest.raises(ValidationError):
        PaymentCreate(method="MTN_MOMO", phone="+256123", email="customer@example.com")
