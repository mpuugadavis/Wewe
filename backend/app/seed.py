import os
from datetime import timedelta

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Block,
    Campus,
    Category,
    CustomerProfile,
    DeliveryAgent,
    DeliveryAssignment,
    DeliveryEarning,
    DeliveryEvent,
    DeliveryPoint,
    Hall,
    Inventory,
    Order,
    OrderItem,
    Payment,
    PickupPoint,
    PlatformSetting,
    Product,
    ProductImage,
    Retailer,
    RetailerFulfillment,
    RetailerProduct,
    University,
    User,
    Review,
    utcnow,
)
from app.security import hash_password


def seed() -> None:
    settings = get_settings()
    if settings.app_env not in {"development", "test"}:
        raise SystemExit("Refusing to seed outside APP_ENV=development or test.")
    password = os.getenv("WEWE_SEED_PASSWORD", "")
    if len(password) < 12:
        raise SystemExit("Set WEWE_SEED_PASSWORD to a value of at least 12 characters.")
    with SessionLocal.begin() as db:
        now = utcnow()
        university = db.scalar(select(University).where(University.slug == "makerere-university"))
        if university is None:
            university = University(name="Makerere University", slug="makerere-university", country_code="UG")
            db.add(university)
            db.flush()
        campus = db.scalar(select(Campus).where(Campus.university_id == university.id, Campus.slug == "main-campus"))
        if campus is None:
            campus = Campus(university_id=university.id, name="Main Campus", slug="main-campus")
            db.add(campus)
            db.flush()
        mulago = db.scalar(select(Campus).where(Campus.university_id == university.id, Campus.slug == "mulago-campus"))
        if mulago is None:
            mulago = Campus(university_id=university.id, name="Mulago Campus", slug="mulago-campus")
            db.add(mulago)
            db.flush()

        hall_records = {}
        for name, kind in (("Africa Hall", "HALL"), ("Complex Hall", "HALL"), ("Livingstone Hall", "HALL"), ("Lumumba Hall", "HALL"), ("Mary Stuart Hall", "HALL"), ("Mitchell Hall", "HALL"), ("Nkrumah Hall", "HALL"), ("Nsibirwa Hall", "HALL"), ("University Hall", "HALL"), ("Makerere International Students Hostel", "HOSTEL"), ("Muhika Hostel", "HOSTEL"), ("JJ Hostel", "HOSTEL"), ("Apex Girls Hostel", "HOSTEL"), ("Makerere Garden Courts", "HOSTEL"), ("Nana Hostel", "HOSTEL"), ("Galloway House", "HOSTEL")):
            hall = db.scalar(select(Hall).where(Hall.campus_id == campus.id, Hall.name == name))
            if hall is None:
                hall = Hall(campus_id=campus.id, name=name, kind=kind)
                db.add(hall)
                db.flush()
            hall_records[name] = hall
        block = db.scalar(select(Block).where(Block.hall_id == hall_records["Livingstone Hall"].id, Block.name == "Block A"))
        if block is None:
            block = Block(hall_id=hall_records["Livingstone Hall"].id, name="Block A")
            db.add(block)
            db.flush()

        # Seed coordinates around Makerere's main campus so the routing service
        # has a real origin and destination to price a road route from.
        def public_point(name: str, kind: str = "BUILDING", hall_id=None, directions=None, latitude=None, longitude=None) -> DeliveryPoint:
            point = db.scalar(select(DeliveryPoint).where(DeliveryPoint.campus_id == campus.id, DeliveryPoint.name == name, DeliveryPoint.owner_user_id.is_(None)))
            if point is None:
                point = DeliveryPoint(campus_id=campus.id, hall_id=hall_id, kind=kind, name=name, directions=directions, latitude=latitude, longitude=longitude, is_private=False)
                db.add(point)
                db.flush()
            else:
                # Canonical public destinations are maintained by the seed.
                # Refresh their coordinates so an older development database
                # cannot retain stale or approximate routing coordinates.
                if latitude is not None:
                    point.latitude = latitude
                if longitude is not None:
                    point.longitude = longitude
                if hall_id is not None:
                    point.hall_id = hall_id
                db.flush()
            return point

        shop_point = public_point("Kikoni shopfront", directions="Opposite the main campus gate", latitude="0.335300", longitude="32.571300")
        curated_coordinates = {
            "Africa Hall": ("0.337890", "32.568910"),
            "Complex Hall": ("0.329530", "32.569750"),
            "Livingstone Hall": ("0.338770", "32.567990"),
            "Lumumba Hall": ("0.331960", "32.566610"),
            "Mary Stuart Hall": ("0.330580", "32.566590"),
            "Mitchell Hall": ("0.3338875", "32.5705214"),
            "Nkrumah Hall": ("0.335840", "32.569380"),
            "Nsibirwa Hall": ("0.336080", "32.569900"),
            "University Hall": ("0.332897", "32.572208"),
        }
        for curated_hall in hall_records.values():
            if curated_hall.kind != "HALL":
                continue
            latitude, longitude = curated_coordinates.get(curated_hall.name, (None, None))
            public_point(
                curated_hall.name,
                kind="BUILDING",
                hall_id=curated_hall.id,
                directions="Makerere University Main Campus",
                latitude=latitude,
                longitude=longitude,
            )
        # Verified/publicly mapped student-hostel coordinates. These are
        # stored as delivery destinations, not as routing distances. The
        # University confirms these hostels are part of the Makerere student
        # accommodation ecosystem; individual coordinates are sourced from
        # public map records and kept to six decimal places.
        hostel_coordinates = {
            "Makerere International Students Hostel": ("0.334990", "32.560500"),
            "Muhika Hostel": ("0.333190", "32.562550"),
            "JJ Hostel": ("0.337670", "32.561720"),
            "Apex Girls Hostel": ("0.333050", "32.562700"),
            "Makerere Garden Courts": ("0.331290", "32.562080"),
            "Nana Hostel": ("0.325474", "32.566765"),
            "Galloway House": ("0.338690", "32.577920"),
        }
        for hostel_name in hostel_coordinates:
            latitude, longitude = hostel_coordinates[hostel_name]
            public_point(
                hostel_name,
                kind="BUILDING",
                directions="Makerere student accommodation area",
                latitude=latitude,
                longitude=longitude,
            )

        # Named surrounding service areas. They remain in the same main-campus
        # delivery catalogue so customers can select a neighborhood without
        # dropping a marker for every possible address.
        service_areas = {
            "Kikoni": ("0.335750", "32.562050"),
            "Wandegeya": ("0.331112", "32.573600"),
            "Kagugube": ("0.326810", "32.567820"),
            "Mulago": ("0.342508", "32.576959"),
            "Makerere": ("0.339656", "32.564142"),
        }
        for area_name, (latitude, longitude) in service_areas.items():
            public_point(
                area_name,
                kind="OTHER",
                directions="Kampala service area",
                latitude=latitude,
                longitude=longitude,
            )
        pickup_location = public_point("Main Library pickup desk", kind="PICKUP_POINT", directions="Ground floor reception", latitude="0.334873", longitude="32.567497")
        pickup = db.get(PickupPoint, pickup_location.id)
        if pickup is None:
            db.add(PickupPoint(delivery_point_id=pickup_location.id, contact_name="WEWE desk", opening_hours={"weekdays": "09:00-18:00", "weekends": "10:00-16:00"}))

        def user(email: str, name: str, phone: str, role: str) -> User:
            result = db.scalar(select(User).where(User.email == email))
            if result is None:
                result = User(name=name, email=email, phone=phone, password_hash=hash_password(password), role=role, status="ACTIVE", email_verified_at=now, phone_verified_at=now)
                db.add(result)
                db.flush()
            return result

        admin_user = user("admin@wewe.test", "WEWE Admin", "+256700000101", "ADMIN")
        customer = user("amina@wewe.test", "Amina N.", "+256700000102", "CUSTOMER")
        retailer_user = user("shop@wewe.test", "Sarah K.", "+256700000103", "RETAILER")
        agent_user = user("rider@wewe.test", "Brian K.", "+256700000104", "DELIVERY_AGENT")
        user("daniel@wewe.test", "Daniel O.", "+256700000105", "CUSTOMER")
        kitchen_user = user("food@wewe.test", "Grace A.", "+256700000106", "RETAILER")
        creative_user = user("creatives@wewe.test", "Mariam T.", "+256700000107", "RETAILER")
        bookshop_user = user("books@wewe.test", "Peter M.", "+256700000108", "RETAILER")
        second_agent_user = user("rider2@wewe.test", "Joel S.", "+256700000109", "DELIVERY_AGENT")

        def retailer_profile(owner: User, name: str, slug: str, description: str) -> Retailer:
            profile = db.scalar(select(Retailer).where(Retailer.user_id == owner.id))
            if profile is None:
                profile = Retailer(user_id=owner.id, business_name=name, slug=slug, description=description, phone=owner.phone, location_id=shop_point.id, verification_status="VERIFIED", status="ACTIVE")
                db.add(profile)
                db.flush()
            return profile

        retailers = {
            "Clothing": retailer_profile(retailer_user, "Thread Theory UG", "thread-theory-ug", "Everyday campuswear, made in Kampala."),
            "Food": retailer_profile(kitchen_user, "Nakulabye Kitchen", "nakulabye-kitchen", "Fresh campus meals, made to order."),
            "Accessories": retailer_profile(creative_user, "MUG Creatives", "mug-creatives", "Student-made everyday finds."),
            "Stationery": retailer_profile(bookshop_user, "Campus Bookshop", "campus-bookshop", "Study essentials for every semester."),
        }
        agent = db.get(DeliveryAgent, agent_user.id)
        if agent is None:
            agent = DeliveryAgent(user_id=agent_user.id, phone=agent_user.phone, verification_status="VERIFIED", availability_status="AVAILABLE", transport_mode="BICYCLE")
            db.add(agent)
        second_agent = db.get(DeliveryAgent, second_agent_user.id)
        if second_agent is None:
            db.add(DeliveryAgent(user_id=second_agent_user.id, phone=second_agent_user.phone, verification_status="PENDING", availability_status="OFFLINE", transport_mode="WALKING"))
        customer_profile = db.get(CustomerProfile, customer.id)
        if customer_profile is None:
            customer_profile = CustomerProfile(user_id=customer.id)
            db.add(customer_profile)
        daniel = db.scalar(select(User).where(User.email == "daniel@wewe.test"))
        if db.get(CustomerProfile, daniel.id) is None:
            db.add(CustomerProfile(user_id=daniel.id))

        private_room = db.scalar(select(DeliveryPoint).where(DeliveryPoint.owner_user_id == customer.id, DeliveryPoint.name == "Room 12"))
        if private_room is None:
            private_room = DeliveryPoint(campus_id=campus.id, hall_id=hall_records["Livingstone Hall"].id, block_id=block.id, owner_user_id=customer.id, kind="ROOM", name="Room 12", directions="Livingstone Hall, Block A", latitude="0.331700", longitude="32.574400", is_private=True)
            db.add(private_room)
            db.flush()
        elif private_room.latitude is None or private_room.longitude is None:
            private_room.latitude = private_room.latitude or "0.331700"
            private_room.longitude = private_room.longitude or "32.574400"
            db.flush()
        customer_profile.preferred_delivery_point_id = private_room.id

        category_names = ["Food", "Clothing", "Shoes", "Electronics", "Stationery", "Beauty", "Accessories"]
        categories = {}
        for index, name in enumerate(category_names):
            slug = name.lower()
            category = db.scalar(select(Category).where(Category.slug == slug))
            if category is None:
                category = Category(name=name, slug=slug, sort_order=index)
                db.add(category)
                db.flush()
            categories[name] = category

        seeded_products = []
        product_data = [
            ("Campus Classic Hoodie", "Soft cotton-blend campus hoodie.", "Clothing", 65000, 24),
            ("Chicken & Chips Combo", "Fresh chicken and golden chips.", "Food", 18000, 20),
            ("Everyday Canvas Tote", "Durable everyday campus tote.", "Accessories", 22000, 12),
            ("Study Notes Bundle", "Ruled notebooks and study essentials.", "Stationery", 15000, 35),
        ]
        for name, description, category_name, price, quantity in product_data:
            product = db.scalar(select(Product).where(Product.name == name, Product.category_id == categories[category_name].id))
            if product is None:
                product = Product(name=name, description=description, category_id=categories[category_name].id, status="ACTIVE")
                db.add(product)
                db.flush()
            retailer = retailers[category_name]
            listing = db.scalar(select(RetailerProduct).where(RetailerProduct.retailer_id == retailer.id, RetailerProduct.product_id == product.id))
            if listing is None:
                listing = RetailerProduct(retailer_id=retailer.id, product_id=product.id, sku=name.upper().replace(" ", "-")[:100], price_ugx=price, is_active=True)
                db.add(listing)
                db.flush()
                db.add(Inventory(product_id=product.id, retailer_id=retailer.id, retailer_product_id=listing.id, owner_type="RETAILER", quantity=quantity, reserved_quantity=0))
            if db.scalar(select(ProductImage.id).where(ProductImage.product_id == product.id)) is None:
                demo_image_urls = {
                    "Campus Classic Hoodie": "https://images.unsplash.com/photo-1521803751845-f36d43bb1f76?auto=format&fit=crop&w=1200&q=85",
                    "Chicken & Chips Combo": "https://images.unsplash.com/photo-1548340748-6d2b7d7da280?auto=format&fit=crop&w=1200&q=85",
                    "Everyday Canvas Tote": "https://images.unsplash.com/photo-1780480999314-b82a1f2f9de6?auto=format&fit=crop&w=1200&q=85",
                    "Study Notes Bundle": "https://images.unsplash.com/photo-1764818959104-995873e9add5?auto=format&fit=crop&w=1200&q=85",
                }
                image_url = demo_image_urls.get(name)
                if image_url:
                    db.add(ProductImage(product_id=product.id, url=image_url, alt_text=name, sort_order=0))
            seeded_products.append((product, listing))

        setting = db.get(PlatformSetting, "delivery_fee_ugx")
        if setting is None:
            db.add(PlatformSetting(key="delivery_fee_ugx", value={"amount": 3500}, updated_by=admin_user.id))

        sample_order = db.scalar(select(Order).where(Order.order_number == "WW-SEED0001"))
        if sample_order is None:
            hoodie, hoodie_listing = seeded_products[0]
            hoodie_retailer = retailers["Clothing"]
            inventory = db.scalar(select(Inventory).where(Inventory.retailer_product_id == hoodie_listing.id))
            inventory.quantity = max(0, inventory.quantity - 1)
            sample_order = Order(order_number="WW-SEED0001", customer_id=customer.id, delivery_point_id=private_room.id, delivery_method="DELIVERY", currency="UGX", subtotal_ugx=hoodie_listing.price_ugx, delivery_fee_ugx=3500, total_ugx=hoodie_listing.price_ugx + 3500, status="DELIVERED", payment_status="PAID", confirmed_at=now, delivered_at=now)
            db.add(sample_order)
            db.flush()
            order_item = OrderItem(order_id=sample_order.id, product_id=hoodie.id, retailer_product_id=hoodie_listing.id, retailer_id=hoodie_retailer.id, product_name=hoodie.name, sku_snapshot=hoodie_listing.sku, unit_price_ugx=hoodie_listing.price_ugx, quantity=1, line_total_ugx=hoodie_listing.price_ugx)
            db.add(order_item)
            db.flush()
            fulfillment = RetailerFulfillment(order_id=sample_order.id, retailer_id=hoodie_retailer.id, status="DELIVERED", confirmed_at=now, ready_at=now)
            db.add(fulfillment)
            db.flush()
            assignment = DeliveryAssignment(fulfillment_id=fulfillment.id, agent_id=agent_user.id, pickup_point_id=shop_point.id, dropoff_point_id=private_room.id, status="DELIVERED", assigned_at=now, accepted_at=now, picked_up_at=now, delivered_at=now)
            db.add(assignment)
            db.flush()
            db.add(DeliveryEvent(assignment_id=assignment.id, actor_user_id=agent_user.id, previous_status="OUT_FOR_DELIVERY", new_status="DELIVERED"))
            db.add(DeliveryEarning(assignment_id=assignment.id, agent_id=agent_user.id, amount_ugx=3500, status="PENDING"))
            db.add(Payment(order_id=sample_order.id, customer_id=customer.id, amount_ugx=sample_order.total_ugx, currency="UGX", method="MTN_MOMO", provider="MTN_MOMO", provider_reference="seed-momo-reference", status="SUCCESSFUL", paid_at=now))
            db.add(Review(product_id=hoodie.id, customer_id=customer.id, order_item_id=order_item.id, rating=5, body="Warm, comfortable, and right on time.", moderation_status="VISIBLE"))
    print("WEWE development data is ready. Use the seed users documented in README.md with WEWE_SEED_PASSWORD.")


if __name__ == "__main__":
    seed()
