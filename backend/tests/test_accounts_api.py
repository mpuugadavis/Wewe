from sqlalchemy import event

from app.models import Category, Product, Retailer, RetailerProduct, User
from app.security import hash_password


def test_public_retailer_product_counts_use_one_aggregate_query(client, database) -> None:
    category = Category(name="Retailer API Category", slug="retailer-api-category")
    database.add(category)
    database.flush()
    expected_slugs = []
    for index in (1, 2):
        owner = User(
            name=f"Retailer API Owner {index}",
            email=f"retailer-api-{index}@example.test",
            phone=f"+25670000020{index}",
            password_hash=hash_password("strong-campus-password-42"),
            role="RETAILER",
            status="ACTIVE",
        )
        database.add(owner)
        database.flush()
        retailer = Retailer(
            user_id=owner.id,
            business_name=f"Retailer API Shop {index}",
            slug=f"retailer-api-shop-{index}",
            phone=owner.phone,
            verification_status="VERIFIED",
            status="ACTIVE",
        )
        product = Product(
            category_id=category.id,
            name=f"Retailer API Product {index}",
            status="ACTIVE",
        )
        database.add_all([retailer, product])
        database.flush()
        database.add(
            RetailerProduct(
                retailer_id=retailer.id,
                product_id=product.id,
                price_ugx=1000,
                is_active=True,
            )
        )
        expected_slugs.append(retailer.slug)
    database.commit()

    aggregate_queries = []

    def count_aggregate_queries(_conn, _cursor, statement, _params, _context, _executemany):
        if "count(retailer_products.id)" in statement.lower():
            aggregate_queries.append(statement)

    event.listen(database.get_bind(), "before_cursor_execute", count_aggregate_queries)
    try:
        response = client.get("/api/v1/retailers")
    finally:
        event.remove(database.get_bind(), "before_cursor_execute", count_aggregate_queries)

    assert response.status_code == 200
    matching_retailers = [retailer for retailer in response.json() if retailer["slug"] in expected_slugs]
    assert len(matching_retailers) == 2
    assert all(retailer["product_count"] == 1 for retailer in matching_retailers)
    assert len(aggregate_queries) == 1
