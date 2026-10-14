from sqlalchemy import select, func
from app.models import Category, Retailer, RetailerProduct, Product, ProductImage, User
from app.seed_catalog import seed_catalog
from test_order_service import marketplace_fixture, _authorization
import pytest


def test_verified_retailer_can_create_reuse_and_assign_category(client, database):
    marketplace_fixture(database)
    owner = database.scalar(select(User).where(User.role == "RETAILER"))
    headers = _authorization(database, owner)
    first = client.post("/api/v1/retailers/me/categories", headers=headers, json={"name": "  Home   essentials  "})
    assert first.status_code == 200, first.text
    assert first.json()["name"] == "Home essentials"
    again = client.post("/api/v1/retailers/me/categories", headers=headers, json={"name": "home essentials"})
    assert again.json()["id"] == first.json()["id"]
    response = client.post("/api/v1/retailers/me/products", headers=headers, json={"name": "Desk lamp", "description": "Adjustable lamp", "category_id": first.json()["id"], "price_ugx": 25000, "stock_quantity": 5})
    assert response.status_code == 201, response.text
    assert response.json()["category_id"] == first.json()["id"]


def test_category_creation_respects_role_verification_and_inactive_categories(client, database):
    customer, _, _, _ = marketplace_fixture(database)
    assert client.post("/api/v1/retailers/me/categories", headers=_authorization(database, customer), json={"name":"New category"}).status_code == 403
    owner = database.scalar(select(User).where(User.role == "RETAILER"))
    headers = _authorization(database, owner)
    category = database.scalar(select(Category))
    category.is_active = False
    database.commit()
    assert client.post("/api/v1/retailers/me/categories", headers=headers, json={"name":category.name}).status_code == 409
    assert client.post("/api/v1/retailers/me/categories", headers=headers, json={"name":"  "}).status_code == 422
    retailer = database.scalar(select(Retailer))
    retailer.verification_status = "PENDING"
    database.commit()
    assert client.post("/api/v1/retailers/me/categories", headers=headers, json={"name":"New category"}).status_code == 403


def test_demo_catalogue_is_repeatable_and_forbidden_in_production(database):
    marketplace_fixture(database)
    original = database.scalar(select(func.count()).select_from(Product))
    assert seed_catalog(database, environment="test") == 28
    database.commit()
    demo_ids = select(RetailerProduct.product_id).where(RetailerProduct.sku.like("DEMO-%"))
    demo_images = database.scalars(select(ProductImage).where(ProductImage.product_id.in_(demo_ids))).all()
    assert len(demo_images) == 28
    assert len({image.url for image in demo_images}) == 28
    demo_images[0].url = "https://images.unsplash.com/old-shared-photo"
    assert seed_catalog(database, environment="test", refresh_demo_images=True) == 0
    assert "old-shared-photo" not in demo_images[0].url
    assert seed_catalog(database, environment="test") == 0
    assert database.scalar(select(func.count()).select_from(Product)) == original + 28
    assert database.scalar(select(func.count()).select_from(Retailer).where(Retailer.slug.like("demo-%"))) == 7
    with pytest.raises(ValueError, match="forbidden"):
        seed_catalog(database, environment="production")
