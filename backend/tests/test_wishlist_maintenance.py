from sqlalchemy import select
from app.models import AuditLog, PlatformSetting, Product, User
from app.security import hash_password
from test_order_service import marketplace_fixture, _authorization


def admin_headers(database):
    user = User(name="Admin", email="admin@test.invalid", role="ADMIN", status="ACTIVE", password_hash=hash_password("test-admin-password"))
    database.add(user)
    database.flush()
    return _authorization(database, user)


def test_wishlist_save_details_isolation_remove_and_roles(client, database):
    customer, _, listing, _ = marketplace_fixture(database)
    headers = _authorization(database, customer)
    product_id = str(listing.product_id)
    for _ in range(2):
        saved = client.post("/api/v1/wishlist", headers=headers, json={"product_id": product_id})
        assert saved.status_code == 201, saved.text
    items = client.get("/api/v1/wishlist", headers=headers).json()
    assert len(items) == 1
    assert items[0]["product_id"] == product_id
    assert items[0]["name"] == "Notebook"
    assert items[0]["listings"][0]["price_ugx"] == 12000
    assert "images" in items[0]
    other = User(name="Other", email="other@test.invalid", role="CUSTOMER", status="ACTIVE", password_hash=hash_password("other-password"))
    database.add(other)
    database.flush()
    other_headers = _authorization(database, other)
    assert client.get("/api/v1/wishlist", headers=other_headers).json() == []
    assert client.delete("/api/v1/wishlist/" + product_id, headers=other_headers).status_code == 204
    assert len(client.get("/api/v1/wishlist", headers=headers).json()) == 1
    owner = database.scalar(select(User).where(User.role == "RETAILER"))
    assert client.post("/api/v1/wishlist", headers=_authorization(database, owner), json={"product_id": product_id}).status_code == 403
    assert client.post("/api/v1/wishlist", json={"product_id": product_id}).status_code == 401
    assert client.delete("/api/v1/wishlist/" + product_id, headers=headers).status_code == 204
    assert client.get("/api/v1/wishlist", headers=headers).json() == []
    product = database.get(Product, listing.product_id)
    product.status = "INACTIVE"
    database.commit()
    assert client.post("/api/v1/wishlist", headers=headers, json={"product_id": product_id}).status_code == 404


def test_maintenance_admin_switch_status_access_and_recovery(client, database):
    customer, _, _, _ = marketplace_fixture(database)
    headers = admin_headers(database)
    customer_headers = _authorization(database, customer)
    assert client.get("/api/v1/system/status").json()["maintenance"] is False
    response = client.put("/api/v1/admin/settings/maintenance", headers=headers, json={"value": {"enabled": True, "message": "Upgrading WEWE"}})
    assert response.status_code == 200, response.text
    status = client.get("/api/v1/system/status")
    assert status.json() == {"maintenance": True, "message": "Upgrading WEWE"}
    assert status.headers["cache-control"] == "no-store"
    for path, access in [("/api/v1/products", {}), ("/api/v1/orders", customer_headers)]:
        response = client.get(path, headers=access)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "maintenance"
        assert response.headers["retry-after"] == "60"
    assert client.post("/api/v1/orders", headers=customer_headers, json={}).status_code == 503
    assert client.get("/api/v1/products", headers=headers).status_code == 200
    assert client.get("/api/v1/admin/settings", headers=headers).status_code == 200
    assert client.get("/api/v1/auth/me", headers=customer_headers).status_code == 200
    assert client.post("/api/v1/auth/login", json={"identifier": "admin@test.invalid", "password": "test-admin-password"}).status_code == 200
    for path in ["/api/v1/payments/pawapay/deposit-callback", "/api/v1/payments/pawapay/checkout-callback", "/api/v1/payments/pawapay/payout-callback", "/api/v1/payments/pawapay/refund-callback", "/api/v1/payments/flutterwave/webhook", "/api/v1/payments/webhooks/PAWAPAY"]:
        assert client.post(path, json={}).status_code != 503, path
    response = client.put("/api/v1/admin/settings/maintenance", headers=headers, json={"value": {"enabled": False}})
    assert response.status_code == 200
    assert client.get("/api/v1/products").status_code == 200
    assert client.get("/api/v1/system/status").json()["maintenance"] is False
    assert len(database.scalars(select(AuditLog).where(AuditLog.resource_id == "maintenance")).all()) == 2


def test_maintenance_validation_and_nonadmin_permissions(client, database):
    customer, _, _, _ = marketplace_fixture(database)
    headers = admin_headers(database)
    assert client.put("/api/v1/admin/settings/maintenance", headers=_authorization(database, customer), json={"value": {"enabled": True}}).status_code == 403
    for value in [{"enabled": "true"}, {"enabled": True, "message": "x" * 501}, {"enabled": True, "message": 5}, {"message": "missing enabled"}, {"enabled": True, "unexpected": True}]:
        assert client.put("/api/v1/admin/settings/maintenance", headers=headers, json={"value": value}).status_code == 422
    assert database.get(PlatformSetting, "maintenance") is None
