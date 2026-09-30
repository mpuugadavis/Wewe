"""Cart regression tests for the WEWE customer basket.

The cart is working functionality. These tests pin its behaviour so that later
schema, checkout or payment work cannot silently break it.

Authentication tokens are issued directly through the same helpers the API
uses, so the tests do not depend on the rate-limited auth endpoints.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Cart,
    CartItem,
    Campus,
    Category,
    CustomerProfile,
    Inventory,
    Product,
    RefreshTokenFamily,
    Retailer,
    RetailerProduct,
    University,
    User,
)
from app.security import create_access_token, hash_password

PASSWORD = "cart-regression-password-42"


def _suffix() -> str:
    return uuid4().hex[:10]


def _phone() -> str:
    return f"+2567{int(uuid4().hex[:9], 16) % 1_000_000_000:09d}"


def _customer(database) -> User:
    suffix = _suffix()
    customer = User(
        name="Cart Customer",
        email=f"cart-customer-{suffix}@test.invalid",
        phone=None,
        password_hash=hash_password(PASSWORD),
        role="CUSTOMER",
        status="ACTIVE",
    )
    database.add(customer)
    database.flush()
    database.add(CustomerProfile(user_id=customer.id))
    database.flush()
    return customer


def _auth_headers(database, user: User) -> dict[str, str]:
    family = RefreshTokenFamily(user_id=user.id, token_version=user.token_version)
    database.add(family)
    database.flush()
    token = create_access_token(user.id, user.token_version, family.id)
    return {"Authorization": f"Bearer {token}"}


def _listing(
    database,
    *,
    price_ugx: int = 12_000,
    stock: int = 5,
    listing_active: bool = True,
    product_status: str = "ACTIVE",
    retailer_status: str = "ACTIVE",
    retailer_verification: str = "VERIFIED",
    retailer_user_status: str = "ACTIVE",
) -> dict:
    suffix = _suffix()
    university = University(name=f"University {suffix}", slug=f"university-{suffix}")
    database.add(university)
    database.flush()
    campus = Campus(university_id=university.id, name="Main Campus", slug=f"main-{suffix}")
    category = Category(name=f"Category {suffix}", slug=f"category-{suffix}")
    owner = User(
        name="Shop Owner",
        email=f"shop-owner-{suffix}@test.invalid",
        phone=_phone(),
        password_hash=hash_password(PASSWORD),
        role="RETAILER",
        status=retailer_user_status,
    )
    database.add_all([campus, category, owner])
    database.flush()
    retailer = Retailer(
        user_id=owner.id,
        business_name=f"Shop {suffix}",
        slug=f"shop-{suffix}",
        phone=owner.phone,
        verification_status=retailer_verification,
        status=retailer_status,
    )
    database.add(retailer)
    database.flush()
    product = Product(
        category_id=category.id,
        name=f"Product {suffix}",
        description="Cart regression product",
        status=product_status,
    )
    database.add(product)
    database.flush()
    listing = RetailerProduct(
        retailer_id=retailer.id,
        product_id=product.id,
        sku=f"SKU-{suffix}",
        price_ugx=price_ugx,
        is_active=listing_active,
    )
    database.add(listing)
    database.flush()
    inventory = Inventory(
        product_id=product.id,
        retailer_id=retailer.id,
        retailer_product_id=listing.id,
        owner_type="RETAILER",
        quantity=stock,
        reserved_quantity=0,
    )
    database.add(inventory)
    database.flush()
    return {
        "product": product,
        "listing": listing,
        "inventory": inventory,
        "retailer": retailer,
        "owner": owner,
    }


def _add(client: TestClient, headers: dict, listing_id, quantity: int = 1):
    return client.post(
        "/api/v1/cart/items",
        json={"retailer_product_id": str(listing_id), "quantity": quantity},
        headers=headers,
    )


def _cart_rows(database, customer: User) -> int:
    cart_id = database.scalar(select(Cart.id).where(Cart.customer_id == customer.id))
    if cart_id is None:
        return 0
    return database.scalar(select(func.count(CartItem.id)).where(CartItem.cart_id == cart_id)) or 0


def test_customer_can_retrieve_their_cart(client: TestClient, database) -> None:
    customer = _customer(database)
    headers = _auth_headers(database, customer)
    database.commit()

    response = client.get("/api/v1/cart", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["currency"] == "UGX"
    assert payload["items"] == []
    assert payload["subtotal_ugx"] == 0


def test_customer_can_add_a_listing(client: TestClient, database) -> None:
    customer = _customer(database)
    world = _listing(database)
    headers = _auth_headers(database, customer)
    database.commit()

    response = _add(client, headers, world["listing"].id)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["retailer_product_id"] == str(world["listing"].id)
    assert item["product_id"] == str(world["product"].id)
    assert item["product_name"] == world["product"].name
    assert item["retailer_name"] == world["retailer"].business_name
    assert item["quantity"] == 1
    assert item["unit_price_ugx"] == 12_000
    assert item["line_total_ugx"] == 12_000
    assert item["stock_available"] == 5
    assert payload["subtotal_ugx"] == 12_000
    assert _cart_rows(database, customer) == 1


def test_adding_same_listing_increases_quantity(client: TestClient, database) -> None:
    customer = _customer(database)
    world = _listing(database)
    headers = _auth_headers(database, customer)
    database.commit()

    assert _add(client, headers, world["listing"].id).status_code == 200
    response = _add(client, headers, world["listing"].id)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["quantity"] == 2
    assert payload["items"][0]["line_total_ugx"] == 24_000
    assert payload["subtotal_ugx"] == 24_000
    assert _cart_rows(database, customer) == 1


def test_customer_can_update_quantity(client: TestClient, database) -> None:
    customer = _customer(database)
    world = _listing(database)
    headers = _auth_headers(database, customer)
    database.commit()
    item_id = _add(client, headers, world["listing"].id).json()["items"][0]["id"]

    response = client.patch(f"/api/v1/cart/items/{item_id}", json={"quantity": 3}, headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["quantity"] == 3
    assert payload["items"][0]["line_total_ugx"] == 36_000
    assert payload["subtotal_ugx"] == 36_000
    assert _cart_rows(database, customer) == 1


def test_update_quantity_above_stock_is_rejected(client: TestClient, database) -> None:
    customer = _customer(database)
    world = _listing(database, stock=2)
    headers = _auth_headers(database, customer)
    database.commit()
    item_id = _add(client, headers, world["listing"].id).json()["items"][0]["id"]

    response = client.patch(f"/api/v1/cart/items/{item_id}", json={"quantity": 3}, headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "insufficient_stock"
    assert client.get("/api/v1/cart", headers=headers).json()["items"][0]["quantity"] == 1


def test_customer_can_remove_an_item(client: TestClient, database) -> None:
    customer = _customer(database)
    world = _listing(database)
    headers = _auth_headers(database, customer)
    database.commit()
    item_id = _add(client, headers, world["listing"].id).json()["items"][0]["id"]

    response = client.delete(f"/api/v1/cart/items/{item_id}", headers=headers)

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/api/v1/cart", headers=headers).json()["items"] == []
    assert _cart_rows(database, customer) == 0


def test_removing_an_unknown_item_returns_not_found(client: TestClient, database) -> None:
    customer = _customer(database)
    headers = _auth_headers(database, customer)
    database.commit()

    response = client.delete(f"/api/v1/cart/items/{uuid4()}", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "cart_item_not_found"


def test_customer_can_clear_the_cart(client: TestClient, database) -> None:
    customer = _customer(database)
    first = _listing(database)
    second = _listing(database)
    headers = _auth_headers(database, customer)
    database.commit()
    assert _add(client, headers, first["listing"].id).status_code == 200
    assert _add(client, headers, second["listing"].id).status_code == 200
    assert _cart_rows(database, customer) == 2

    response = client.delete("/api/v1/cart", headers=headers)

    assert response.status_code == 204
    assert client.get("/api/v1/cart", headers=headers).json()["items"] == []
    assert _cart_rows(database, customer) == 0


def test_add_is_rejected_when_stock_is_insufficient(client: TestClient, database) -> None:
    customer = _customer(database)
    world = _listing(database, stock=2)
    headers = _auth_headers(database, customer)
    database.commit()

    response = _add(client, headers, world["listing"].id, quantity=3)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "insufficient_stock"
    assert _cart_rows(database, customer) == 0

    # Stock is cumulative across successive adds.
    assert _add(client, headers, world["listing"].id).status_code == 200
    assert _add(client, headers, world["listing"].id).status_code == 200
    third = _add(client, headers, world["listing"].id)
    assert third.status_code == 409
    assert third.json()["error"]["code"] == "insufficient_stock"
    assert client.get("/api/v1/cart", headers=headers).json()["items"][0]["quantity"] == 2


@pytest.mark.parametrize(
    "unavailable",
    [
        pytest.param({"listing_active": False}, id="inactive-listing"),
        pytest.param({"product_status": "DRAFT"}, id="draft-product"),
        pytest.param({"product_status": "INACTIVE"}, id="inactive-product"),
        pytest.param({"retailer_status": "INACTIVE"}, id="inactive-retailer"),
        pytest.param({"retailer_verification": "PENDING"}, id="unverified-retailer"),
        pytest.param({"retailer_user_status": "SUSPENDED"}, id="suspended-retailer-account"),
    ],
)
def test_add_is_rejected_when_listing_is_unavailable(client: TestClient, database, unavailable: dict) -> None:
    customer = _customer(database)
    world = _listing(database, **unavailable)
    headers = _auth_headers(database, customer)
    database.commit()

    response = _add(client, headers, world["listing"].id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "listing_unavailable"
    assert _cart_rows(database, customer) == 0
    assert client.get("/api/v1/cart", headers=headers).json()["items"] == []


def test_add_unknown_listing_returns_not_found(client: TestClient, database) -> None:
    customer = _customer(database)
    headers = _auth_headers(database, customer)
    database.commit()

    response = _add(client, headers, uuid4())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "listing_not_found"


def test_customer_cannot_access_another_customers_cart_item(client: TestClient, database) -> None:
    owner = _customer(database)
    other = _customer(database)
    world = _listing(database)
    owner_headers = _auth_headers(database, owner)
    other_headers = _auth_headers(database, other)
    database.commit()
    item_id = _add(client, owner_headers, world["listing"].id).json()["items"][0]["id"]

    update = client.patch(f"/api/v1/cart/items/{item_id}", json={"quantity": 5}, headers=other_headers)
    removal = client.delete(f"/api/v1/cart/items/{item_id}", headers=other_headers)

    assert update.status_code == 404
    assert update.json()["error"]["code"] == "cart_item_not_found"
    assert removal.status_code == 404
    assert client.get("/api/v1/cart", headers=other_headers).json()["items"] == []

    # The other customer's cart is private, and clearing their own cart must not touch the owner's.
    assert client.delete("/api/v1/cart", headers=other_headers).status_code == 204
    owner_items = client.get("/api/v1/cart", headers=owner_headers).json()["items"]
    assert len(owner_items) == 1
    assert owner_items[0]["quantity"] == 1
    assert _cart_rows(database, owner) == 1


def test_cart_subtotal_is_calculated_correctly(client: TestClient, database) -> None:
    customer = _customer(database)
    first = _listing(database, price_ugx=12_000, stock=5)
    second = _listing(database, price_ugx=5_000, stock=5)
    headers = _auth_headers(database, customer)
    database.commit()
    assert _add(client, headers, first["listing"].id, quantity=2).status_code == 200
    assert _add(client, headers, second["listing"].id, quantity=1).status_code == 200

    payload = client.get("/api/v1/cart", headers=headers).json()

    lines = {item["retailer_product_id"]: item for item in payload["items"]}
    assert lines[str(first["listing"].id)]["line_total_ugx"] == 24_000
    assert lines[str(second["listing"].id)]["line_total_ugx"] == 5_000
    assert payload["subtotal_ugx"] == 29_000
    assert sum(item["line_total_ugx"] for item in payload["items"]) == payload["subtotal_ugx"]


def test_cart_item_uniqueness_is_preserved(client: TestClient, database) -> None:
    customer = _customer(database)
    world = _listing(database)
    headers = _auth_headers(database, customer)
    database.commit()

    for _ in range(3):
        assert _add(client, headers, world["listing"].id).status_code == 200

    assert _cart_rows(database, customer) == 1
    cart_id = database.scalar(select(Cart.id).where(Cart.customer_id == customer.id))
    with pytest.raises(IntegrityError):
        database.add(CartItem(cart_id=cart_id, retailer_product_id=world["listing"].id, quantity=1))
        database.flush()
    database.rollback()
    assert _cart_rows(database, customer) == 1


def test_cart_requires_an_authenticated_customer(client: TestClient, database) -> None:
    world = _listing(database)
    retailer_headers = _auth_headers(database, world["owner"])
    database.commit()

    item_payload = {"retailer_product_id": str(world["listing"].id), "quantity": 1}
    assert client.get("/api/v1/cart").status_code == 401
    assert client.post("/api/v1/cart/items", json=item_payload).status_code == 401
    assert client.get("/api/v1/cart", headers=retailer_headers).status_code == 403
    assert client.post("/api/v1/cart/items", json=item_payload, headers=retailer_headers).status_code == 403
    assert client.delete("/api/v1/cart", headers=retailer_headers).status_code == 403
