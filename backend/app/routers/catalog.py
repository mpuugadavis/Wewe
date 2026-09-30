from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import Principal, require_roles
from app.models import (
    Category,
    Inventory,
    Product,
    ProductImage,
    Retailer,
    RetailerProduct,
    User,
)
from app.schemas import CategoryOut, ProductCreate, ProductOut, ProductUpdate

router = APIRouter(tags=["catalog"])


def _owned_retailer(db: Session, user_id: UUID) -> Retailer:
    retailer = db.scalar(select(Retailer).where(Retailer.user_id == user_id))
    if retailer is None:
        raise HTTPException(status_code=404, detail={"code": "retailer_profile_missing", "message": "Retailer profile was not found."})
    if retailer.status != "ACTIVE" or retailer.verification_status != "VERIFIED":
        raise HTTPException(status_code=403, detail={"code": "retailer_not_verified", "message": "A verified, active retailer is required."})
    return retailer


def _listing_rows(db: Session, product_ids: list[UUID]) -> dict[UUID, list[dict]]:
    if not product_ids:
        return {}
    rows = db.execute(
        select(RetailerProduct, Retailer, Inventory)
        .join(Retailer, Retailer.id == RetailerProduct.retailer_id)
        .join(User, User.id == Retailer.user_id)
        .outerjoin(Inventory, Inventory.retailer_product_id == RetailerProduct.id)
        .where(
            RetailerProduct.product_id.in_(product_ids),
            RetailerProduct.is_active.is_(True),
            Retailer.status == "ACTIVE",
            Retailer.verification_status == "VERIFIED",
            User.status == "ACTIVE",
        )
    ).all()
    output: dict[UUID, list[dict]] = {}
    for listing, retailer, inventory in rows:
        available = max(0, (inventory.quantity - inventory.reserved_quantity)) if inventory else 0
        output.setdefault(listing.product_id, []).append(
            {
                "retailer_product_id": listing.id,
                "retailer_id": retailer.id,
                "retailer_name": retailer.business_name,
                "retailer_slug": retailer.slug,
                "price_ugx": listing.price_ugx,
                "sku": listing.sku,
                "stock_available": available,
            }
        )
    return output


def _serialize_products(db: Session, products: list[Product]) -> list[dict]:
    if not products:
        return []
    ids = [product.id for product in products]
    images = db.scalars(
        select(ProductImage).where(ProductImage.product_id.in_(ids)).order_by(ProductImage.sort_order)
    ).all()
    images_by_product: dict[UUID, list[str]] = {}
    for image in images:
        images_by_product.setdefault(image.product_id, []).append(image.url)
    listings = _listing_rows(db, ids)
    return [
        {
            "id": product.id,
            "category_id": product.category_id,
            "name": product.name,
            "description": product.description,
            "images": images_by_product.get(product.id, []),
            "listings": listings.get(product.id, []),
        }
        for product in products
    ]


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)) -> list[Category]:
    return list(db.scalars(select(Category).where(Category.is_active.is_(True)).order_by(Category.sort_order, Category.name)).all())


@router.get("/products", response_model=list[ProductOut])
def list_products(
    q: str | None = Query(default=None, max_length=120),
    category_id: UUID | None = None,
    retailer_id: UUID | None = None,
    min_price_ugx: int | None = Query(default=None, ge=0),
    max_price_ugx: int | None = Query(default=None, ge=0),
    in_stock: bool = False,
    sort: str = Query(default="newest", pattern="^(newest|price_asc|price_desc|name)$"),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    if min_price_ugx is not None and max_price_ugx is not None and min_price_ugx > max_price_ugx:
        raise HTTPException(status_code=422, detail={"code": "invalid_price_range", "message": "Minimum price cannot exceed maximum price."})
    listing_statement = (
        select(Product.id)
        .join(RetailerProduct, RetailerProduct.product_id == Product.id)
        .join(Retailer, Retailer.id == RetailerProduct.retailer_id)
        .join(User, User.id == Retailer.user_id)
        .outerjoin(Inventory, Inventory.retailer_product_id == RetailerProduct.id)
        .where(
            Product.status == "ACTIVE",
            RetailerProduct.is_active.is_(True),
            Retailer.status == "ACTIVE",
            Retailer.verification_status == "VERIFIED",
            User.status == "ACTIVE",
        )
    )
    if q:
        pattern = f"%{q.strip()}%"
        listing_statement = listing_statement.where(or_(Product.name.ilike(pattern), Product.description.ilike(pattern), Retailer.business_name.ilike(pattern)))
    if category_id:
        listing_statement = listing_statement.where(Product.category_id == category_id)
    if retailer_id:
        listing_statement = listing_statement.where(Retailer.id == retailer_id)
    if min_price_ugx is not None:
        listing_statement = listing_statement.where(RetailerProduct.price_ugx >= min_price_ugx)
    if max_price_ugx is not None:
        listing_statement = listing_statement.where(RetailerProduct.price_ugx <= max_price_ugx)
    if in_stock:
        listing_statement = listing_statement.where(Inventory.id.is_not(None), Inventory.quantity > Inventory.reserved_quantity)
    matching_ids = listing_statement.distinct().subquery()
    statement = select(Product).where(Product.id.in_(select(matching_ids.c.id)))
    lowest_price = (
        select(func.min(RetailerProduct.price_ugx))
        .join(Retailer, Retailer.id == RetailerProduct.retailer_id)
        .join(User, User.id == Retailer.user_id)
        .outerjoin(Inventory, Inventory.retailer_product_id == RetailerProduct.id)
        .where(
            RetailerProduct.product_id == Product.id,
            RetailerProduct.is_active.is_(True),
            Retailer.status == "ACTIVE",
            Retailer.verification_status == "VERIFIED",
            User.status == "ACTIVE",
        )
    )
    if retailer_id:
        lowest_price = lowest_price.where(Retailer.id == retailer_id)
    if min_price_ugx is not None:
        lowest_price = lowest_price.where(RetailerProduct.price_ugx >= min_price_ugx)
    if max_price_ugx is not None:
        lowest_price = lowest_price.where(RetailerProduct.price_ugx <= max_price_ugx)
    if in_stock:
        lowest_price = lowest_price.where(Inventory.id.is_not(None), Inventory.quantity > Inventory.reserved_quantity)
    lowest_price = lowest_price.correlate(Product).scalar_subquery()
    if sort == "price_asc":
        statement = statement.order_by(lowest_price.asc(), Product.name.asc())
    elif sort == "price_desc":
        statement = statement.order_by(lowest_price.desc(), Product.name.asc())
    elif sort == "name":
        statement = statement.order_by(Product.name.asc())
    else:
        statement = statement.order_by(Product.created_at.desc())
    products = list(db.scalars(statement.offset(offset).limit(limit)).all())
    return _serialize_products(db, products)


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: UUID, db: Session = Depends(get_db)) -> dict:
    product = db.scalar(select(Product).where(Product.id == product_id, Product.status == "ACTIVE"))
    if product is None:
        raise HTTPException(status_code=404, detail={"code": "product_not_found", "message": "Product was not found."})
    return _serialize_products(db, [product])[0]


@router.get("/retailers/me/products", response_model=list[dict])
def retailer_products(
    principal: Principal = Depends(require_roles("RETAILER")),
    db: Session = Depends(get_db),
) -> list[dict]:
    retailer = db.scalar(select(Retailer).where(Retailer.user_id == principal.user.id))
    if retailer is None:
        raise HTTPException(status_code=404, detail="Retailer profile was not found.")
    products = list(
        db.scalars(
            select(Product)
            .join(RetailerProduct, RetailerProduct.product_id == Product.id)
            .where(RetailerProduct.retailer_id == retailer.id)
            .order_by(Product.created_at.desc())
        ).all()
    )
    return _serialize_products(db, products)


@router.post("/retailers/me/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    principal: Principal = Depends(require_roles("RETAILER")),
    db: Session = Depends(get_db),
) -> dict:
    retailer = _owned_retailer(db, principal.user.id)
    category = db.get(Category, payload.category_id)
    if category is None or not category.is_active:
        raise HTTPException(status_code=422, detail={"code": "invalid_category", "message": "Choose an active category."})
    product = Product(category_id=category.id, name=payload.name.strip(), description=payload.description, status="ACTIVE")
    db.add(product)
    db.flush()
    listing = RetailerProduct(
        retailer_id=retailer.id,
        product_id=product.id,
        sku=payload.sku,
        price_ugx=payload.price_ugx,
        is_active=True,
    )
    db.add(listing)
    db.flush()
    db.add(
        Inventory(
            product_id=product.id,
            retailer_id=retailer.id,
            retailer_product_id=listing.id,
            owner_type="RETAILER",
            quantity=payload.stock_quantity,
            reserved_quantity=0,
        )
    )
    db.add_all(
        ProductImage(product_id=product.id, url=url, sort_order=index)
        for index, url in enumerate(payload.image_urls)
    )
    db.commit()
    db.refresh(product)
    return _serialize_products(db, [product])[0]


@router.patch("/retailers/me/products/{listing_id}", response_model=ProductOut)
def update_product(
    listing_id: UUID,
    payload: ProductUpdate,
    principal: Principal = Depends(require_roles("RETAILER")),
    db: Session = Depends(get_db),
) -> dict:
    retailer = _owned_retailer(db, principal.user.id)
    listing = db.scalar(
        select(RetailerProduct).where(RetailerProduct.id == listing_id, RetailerProduct.retailer_id == retailer.id).with_for_update()
    )
    if listing is None:
        raise HTTPException(status_code=404, detail={"code": "listing_not_found", "message": "Product listing was not found."})
    product = db.get(Product, listing.product_id)
    inventory = db.scalar(select(Inventory).where(Inventory.retailer_product_id == listing.id).with_for_update())
    changes = payload.model_dump(exclude_unset=True)
    if "category_id" in changes:
        category = db.get(Category, changes["category_id"])
        if category is None or not category.is_active:
            raise HTTPException(status_code=422, detail={"code": "invalid_category", "message": "Choose an active category."})
        product.category_id = category.id
    for key in ("name", "description"):
        if key in changes:
            setattr(product, key, changes[key].strip() if key == "name" and changes[key] else changes[key])
    if "price_ugx" in changes:
        listing.price_ugx = changes["price_ugx"]
    if "sku" in changes:
        listing.sku = changes["sku"]
    if "is_active" in changes:
        listing.is_active = changes["is_active"]
    if "stock_quantity" in changes:
        if inventory is None:
            raise HTTPException(status_code=409, detail={"code": "inventory_missing", "message": "Inventory record is missing."})
        if changes["stock_quantity"] < inventory.reserved_quantity:
            raise HTTPException(status_code=409, detail={"code": "stock_reserved", "message": "Stock cannot be reduced below quantities reserved by open orders."})
        inventory.quantity = changes["stock_quantity"]
    db.commit()
    db.refresh(product)
    return _serialize_products(db, [product])[0]


@router.delete("/retailers/me/products/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_product(
    listing_id: UUID,
    principal: Principal = Depends(require_roles("RETAILER")),
    db: Session = Depends(get_db),
) -> None:
    retailer = _owned_retailer(db, principal.user.id)
    listing = db.scalar(select(RetailerProduct).where(RetailerProduct.id == listing_id, RetailerProduct.retailer_id == retailer.id))
    if listing is None:
        raise HTTPException(status_code=404, detail={"code": "listing_not_found", "message": "Product listing was not found."})
    listing.is_active = False
    db.commit()
