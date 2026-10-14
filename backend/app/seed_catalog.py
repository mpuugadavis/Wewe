"""Idempotent, non-production catalogue only. Never creates payments or orders."""
import secrets
from sqlalchemy import select
from app.config import get_settings
from app.db import SessionLocal
from app.models import Campus, Category, DeliveryPoint, Inventory, Product, ProductImage, Retailer, RetailerProduct, User
from app.security import hash_password

# Illustrative Unsplash product photography; all shops and listings are samples.
CATALOG = [
    ("Food", "Kikoni Kitchen", "photo-1504674900247-0877df9cc836", [
        ("Grilled chicken lunch bowl", 18000, "Grilled chicken, seasoned rice and fresh seasonal vegetables. Single serving; prepared for lunch."),
        ("Vegetable rice bowl", 12000, "A filling bowl of rice and mixed vegetables. A convenient meat-free campus lunch."),
        ("Lunch for two", 32000, "Two generous rice and chicken servings, packed separately for sharing."),
        ("Fresh garden side salad", 8000, "Crisp greens and seasonal vegetables with dressing supplied separately.")]),
    ("Clothing", "Thread Studio", "photo-1434389677669-e08b4cac3105", [
        ("Everyday cotton knit", 55000, "Soft everyday knit with a relaxed fit. Neutral colour, medium size; gentle cold wash."),
        ("Weekend layer sweater", 68000, "Comfortable long-sleeve layer for cool evenings. Regular fit, large size."),
        ("Campus essential pullover", 45000, "Easy-care casual pullover for lectures and weekends. Medium size."),
        ("Relaxed study-day knit", 62000, "Textured knit with ribbed cuffs and a comfortable neckline. Large size.")]),
    ("Shoes", "Stride Campus", "photo-1542291026-7eec264c27ff", [
        ("Everyday red trainers", 85000, "Lightweight casual trainers with a padded collar. EU 40; lace-up fastening."),
        ("Weekend walking trainers", 78000, "Flexible casual footwear for daily walks. EU 41; cushioned insole."),
        ("Campus commute sneakers", 95000, "Comfortable low-top sneakers with durable soles. EU 42."),
        ("Lightweight active trainers", 110000, "Breathable lace-up trainers for everyday activity. EU 39.")]),
    ("Electronics", "Desk Lab", "photo-1505740420928-5e560c06d30e", [
        ("Over-ear study headphones", 95000, "Padded over-ear headphones for study sessions. Wired audio connection; carry pouch included."),
        ("Everyday audio headphones", 65000, "Adjustable headband and comfortable ear cushions. Standard 3.5 mm audio connection."),
        ("Focus session headphones", 120000, "Closed-back headphones with soft cushions. Suitable for music, calls and recorded lectures."),
        ("Desk audio starter kit", 145000, "Over-ear headphones, audio cable and protective pouch for a simple study setup.")]),
    ("Stationery", "Paper & Pages", "photo-1455390582262-044cdead277a", [
        ("Lecture notebook set", 18000, "Three ruled notebooks for keeping your course notes organised. A5 format."),
        ("Semester planning journal", 22000, "Undated planner with weekly layouts, to-do lists and notes pages."),
        ("Study desk writing bundle", 28000, "Two notebooks and a set of pens for everyday classwork."),
        ("Pocket ideas notebook", 9000, "Compact lined notebook for ideas and reminders. Lightweight soft cover.")]),
    ("Beauty", "Daily Ritual", "photo-1596462502278-27bfdc403348", [
        ("Everyday makeup brush set", 25000, "Soft synthetic brushes for daily makeup application. Wash gently and air dry."),
        ("Travel beauty essentials pouch", 32000, "A practical pouch with a selection of beauty tools for your daily routine."),
        ("Makeup finishing brush", 15000, "A soft synthetic brush for blending powder products. One brush included."),
        ("Vanity brush collection", 45000, "A coordinated selection of face and eye brushes for your dressing table.")]),
    ("Accessories", "Carry Collective", "photo-1553062407-98eeb64c6a62", [
        ("Daily campus backpack", 65000, "Practical backpack with adjustable straps and a roomy main compartment."),
        ("Lecture day carry bag", 55000, "Lightweight everyday bag for notebooks, lunch and small essentials."),
        ("Weekend essentials backpack", 85000, "Versatile carry bag with zipped pockets and padded shoulder straps."),
        ("Compact city backpack", 48000, "A compact bag for light daily loads with easy-access front storage.")]),
]


def seed_catalog(db, *, environment: str):
    if environment not in {"development", "test", "staging"}:
        raise ValueError("Demo catalogue is forbidden in production.")
    campus = db.scalar(select(Campus).order_by(Campus.created_at))
    if campus is None:
        raise ValueError("Create the service campus before adding the demo catalogue.")
    created = 0
    for index, (category_name, shop_name, photo, products) in enumerate(CATALOG):
        category = db.scalar(select(Category).where(Category.slug == category_name.lower()))
        if category is None:
            category = Category(name=category_name, slug=category_name.lower(), sort_order=index)
            db.add(category); db.flush()
        if not category.is_active:
            continue
        slug = "demo-" + shop_name.lower().replace(" & ", "-").replace(" ", "-")
        retailer = db.scalar(select(Retailer).where(Retailer.slug == slug))
        if retailer is None:
            owner = User(name=shop_name + " Demo", email=slug + "@example.invalid", password_hash=hash_password(secrets.token_urlsafe(48)), role="RETAILER", status="ACTIVE")
            db.add(owner); db.flush()
            point = DeliveryPoint(campus_id=campus.id, name=shop_name + " sample pickup", kind="BUILDING", latitude="0.335300", longitude="32.571300", is_private=False, directions="Demo location — not a real shop.")
            db.add(point); db.flush()
            retailer = Retailer(user_id=owner.id, business_name=shop_name + " · Demo", slug=slug, description="Sample shop for demonstrating WEWE. These are not real items for sale.", phone=f"+25670090{index:04d}", location_id=point.id, verification_status="VERIFIED", status="ACTIVE")
            db.add(retailer); db.flush()
        for number, (name, price, description) in enumerate(products):
            sku = f"DEMO-{index + 1:02d}-{number + 1:02d}"
            if db.scalar(select(RetailerProduct.id).where(RetailerProduct.retailer_id == retailer.id, RetailerProduct.sku == sku)):
                continue
            product = Product(name=name, category_id=category.id, description=description + "\n\nDemo listing. Photography is illustrative; this item is not a real offer for sale.", status="ACTIVE")
            db.add(product); db.flush()
            listing = RetailerProduct(product_id=product.id, retailer_id=retailer.id, sku=sku, price_ugx=price, original_price_ugx=(price + price // 5 if number % 2 == 0 else None), is_active=True)
            db.add(listing); db.flush()
            db.add(Inventory(product_id=product.id, retailer_id=retailer.id, retailer_product_id=listing.id, owner_type="RETAILER", quantity=15 + number * 3, reserved_quantity=0))
            for position, width in enumerate([900, 1200]):
                db.add(ProductImage(product_id=product.id, url=f"https://images.unsplash.com/{photo}?auto=format&fit=crop&w={width}&q=85", alt_text=name + " — illustrative demo photo", sort_order=position))
            created += 1
    db.flush()
    return created


def main():
    settings = get_settings()
    with SessionLocal.begin() as db:
        created = seed_catalog(db, environment=settings.app_env)
    print(f"Demo catalogue ready: {created} new products. Existing shops, orders and payments were left unchanged.")


if __name__ == "__main__":
    main()
