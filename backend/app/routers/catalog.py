import io
import re
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
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
from app.schemas import CategoryOut, ProductCreate, ProductImageReorder, ProductOut, ProductUpdate
from app.services.media_storage import (
    MAX_PRODUCT_IMAGES,
    MediaStorageError,
    MediaStorageNotFoundError,
    MediaValidationError,
    build_product_object_key,
    read_upload_with_limit,
    sanitize_image,
)
from app.services.media_uploads import build_media_storage

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
                "original_price_ugx": listing.original_price_ugx,
                "discount_percent": round(((listing.original_price_ugx - listing.price_ugx) / listing.original_price_ugx) * 100) if listing.original_price_ugx and listing.original_price_ugx > listing.price_ugx else 0,
                "sku": listing.sku,
                "stock_available": available,
            }
        )
    return output


def _public_product_image_url(image: ProductImage) -> str:
    """Serve private R2/S3 objects through the existing public catalog endpoint.

    Avoid storing or exposing private-bucket hostnames in customer-facing URLs.
    Keep validated external URLs for legacy catalog images.
    """
    if not image.storage_key:
        return image.url
    version = image.storage_key.rsplit("/", 1)[-1].split(".", 1)[0]
    return f"/api/v1/products/images/{image.id}?v={version}"


def _serialize_products(db: Session, products: list[Product]) -> list[dict]:
    if not products:
        return []
    ids = [product.id for product in products]
    images = db.scalars(
        select(ProductImage).where(ProductImage.product_id.in_(ids)).order_by(ProductImage.sort_order)
    ).all()
    listings = _listing_rows(db, ids)
    return [
        {
            "id": product.id,
            "category_id": product.category_id,
            "name": product.name,
            "description": product.description,
            "images": [
                _public_product_image_url(image)
                for image in images
                if image.product_id == product.id and (image.storage_key or image.url)
            ],
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


@router.get("/products/images/{image_id}")
def read_product_image(
    image_id: UUID,
    background_tasks: BackgroundTasks,
    if_none_match: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Serve stored product media without exposing object-storage credentials."""
    image = db.scalar(
        select(ProductImage)
        .join(Product, Product.id == ProductImage.product_id)
        .where(
            ProductImage.id == image_id,
            Product.status == "ACTIVE",
        )
    )
    if image is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "product_image_not_found", "message": "Product image was not found."},
        )
    if not image.storage_key:
        raise HTTPException(
            status_code=404,
            detail={"code": "stored_media_not_available", "message": "Stored product media is not available."},
        )

    storage = build_media_storage()
    if storage is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "media_storage_unavailable", "message": "Product image storage is not configured."},
        )

    try:
        body, content_type, size_bytes = storage.get(key=image.storage_key)
    except MediaStorageNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "product_image_not_found", "message": "Product image was not found."},
        ) from exc
    except MediaStorageError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "media_storage_error", "message": "Product image storage is temporarily unavailable."},
        ) from exc

    resolved_content_type = (content_type or image.content_type or "").lower()
    allowed_content_types = {"image/jpeg", "image/png", "image/webp"}
    if resolved_content_type not in allowed_content_types:
        body.close()
        raise HTTPException(
            status_code=503,
            detail={"code": "invalid_media_metadata", "message": "Stored product image metadata is invalid."},
        )

    filename_match = re.search(r"([0-9a-f]{64})\.(?:jpg|jpeg|png|webp)$", image.storage_key.lower())
    etag = f'"{filename_match.group(1)}"' if filename_match else None
    if if_none_match:
        requested_tags = {tag.strip() for tag in if_none_match.split(",")}
        if etag in requested_tags or "*" in requested_tags:
            body.close()
            return Response(
                status_code=304,
                headers={
                    "Cache-Control": "public, max-age=31536000, immutable",
                    "ETag": etag,
                    "X-Content-Type-Options": "nosniff",
                    "Cross-Origin-Resource-Policy": "cross-origin",
                },
                background=background_tasks,
            )

    background_tasks.add_task(body.close)
    headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
        "Cross-Origin-Resource-Policy": "cross-origin",
        "Content-Disposition": "inline",
    }
    if size_bytes is not None:
        headers["Content-Length"] = str(size_bytes)
    return StreamingResponse(body, media_type=resolved_content_type, headers=headers, background=background_tasks)


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
        original_price_ugx=payload.original_price_ugx,
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


@router.post("/retailers/me/products/{listing_id}/images", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def upload_product_image(
    listing_id: UUID,
    file: UploadFile = File(...),
    alt_text: str | None = Form(default=None, max_length=250),
    principal: Principal = Depends(require_roles("RETAILER")),
    db: Session = Depends(get_db),
) -> dict:
    retailer = _owned_retailer(db, principal.user.id)
    listing = db.scalar(
        select(RetailerProduct)
        .where(RetailerProduct.id == listing_id, RetailerProduct.retailer_id == retailer.id)
    )
    if listing is None:
        raise HTTPException(status_code=404, detail={"code": "listing_not_found", "message": "Product listing was not found."})

    image_count = db.scalar(
        select(func.count(ProductImage.id)).where(ProductImage.product_id == listing.product_id)
    ) or 0
    if image_count >= MAX_PRODUCT_IMAGES:
        raise HTTPException(
            status_code=409,
            detail={"code": "product_image_limit", "message": f"A product can have at most {MAX_PRODUCT_IMAGES} images."},
        )

    storage = build_media_storage()
    if storage is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "media_storage_unavailable", "message": "Product image uploads are not configured."},
        )

    settings = get_settings()
    try:
        raw = read_upload_with_limit(file.file, max_size_bytes=settings.media_max_upload_bytes)
        sanitized, content_type, extension, width, height = sanitize_image(
            raw,
            declared_content_type=(file.content_type or "").lower(),
            max_size_bytes=settings.media_max_upload_bytes,
        )
        key = build_product_object_key(listing.product_id, sanitized, extension)
    except MediaValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_product_image", "message": str(exc)}) from exc
    finally:
        file.file.close()

    if db.scalar(select(ProductImage.id).where(ProductImage.storage_key == key)) is not None:
        raise HTTPException(status_code=409, detail={"code": "duplicate_product_image", "message": "This image is already attached to the product."})

    next_sort = db.scalar(
        select(func.max(ProductImage.sort_order)).where(ProductImage.product_id == listing.product_id)
    )
    sort_order = (next_sort + 1) if next_sort is not None else 0

    try:
        url = storage.put(
            key=key,
            content=io.BytesIO(sanitized),
            content_type=content_type,
            size_bytes=len(sanitized),
        )
    except MediaStorageError as exc:
        raise HTTPException(status_code=503, detail={"code": "media_storage_error", "message": "Product image storage is temporarily unavailable."}) from exc

    image = ProductImage(
        product_id=listing.product_id,
        url=url,
        alt_text=alt_text.strip() if alt_text else None,
        sort_order=sort_order,
        storage_key=key,
        content_type=content_type,
        size_bytes=len(sanitized),
        width=width,
        height=height,
    )
    db.add(image)
    try:
        db.commit()
    except Exception:
        db.rollback()
        try:
            storage.delete(key=key)
        except MediaStorageError:
            pass
        raise

    product = db.get(Product, listing.product_id)
    return _serialize_products(db, [product])[0]


@router.get("/retailers/me/products/{listing_id}/images", response_model=list[dict])
def list_product_images(
    listing_id: UUID,
    principal: Principal = Depends(require_roles("RETAILER")),
    db: Session = Depends(get_db),
) -> list[dict]:
    retailer = _owned_retailer(db, principal.user.id)
    listing = db.scalar(
        select(RetailerProduct).where(
            RetailerProduct.id == listing_id,
            RetailerProduct.retailer_id == retailer.id,
        )
    )
    if listing is None:
        raise HTTPException(status_code=404, detail={"code": "listing_not_found", "message": "Product listing was not found."})
    images = db.scalars(
        select(ProductImage)
        .where(ProductImage.product_id == listing.product_id)
        .order_by(ProductImage.sort_order, ProductImage.created_at, ProductImage.id)
    ).all()
    return [
        {
            "id": image.id,
            "url": _public_product_image_url(image),
            "alt_text": image.alt_text,
            "sort_order": image.sort_order,
            "content_type": image.content_type,
            "size_bytes": image.size_bytes,
            "width": image.width,
            "height": image.height,
        }
        for image in images
    ]


@router.delete("/retailers/me/products/{listing_id}/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product_image(
    listing_id: UUID,
    image_id: UUID,
    principal: Principal = Depends(require_roles("RETAILER")),
    db: Session = Depends(get_db),
) -> None:
    retailer = _owned_retailer(db, principal.user.id)
    listing = db.scalar(
        select(RetailerProduct)
        .where(RetailerProduct.id == listing_id, RetailerProduct.retailer_id == retailer.id)
        .with_for_update()
    )
    if listing is None:
        raise HTTPException(status_code=404, detail={"code": "listing_not_found", "message": "Product listing was not found."})
    image = db.scalar(
        select(ProductImage)
        .where(ProductImage.id == image_id, ProductImage.product_id == listing.product_id)
        .with_for_update()
    )
    if image is None:
        raise HTTPException(status_code=404, detail={"code": "product_image_not_found", "message": "Product image was not found."})

    storage = build_media_storage() if image.storage_key else None
    storage_key = image.storage_key
    db.delete(image)
    db.flush()
    remaining = db.scalars(
        select(ProductImage)
        .where(ProductImage.product_id == listing.product_id)
        .order_by(ProductImage.sort_order, ProductImage.created_at, ProductImage.id)
        .with_for_update()
    ).all()
    for index, remaining_image in enumerate(remaining):
        remaining_image.sort_order = index
    db.commit()

    if storage is not None and storage_key:
        try:
            storage.delete(key=storage_key)
        except MediaStorageError:
            # The database no longer references the object. Cleanup is best-effort;
            # orphan collection is handled by the storage lifecycle process.
            pass


@router.patch("/retailers/me/products/{listing_id}/images/order", response_model=list[dict])
def reorder_product_images(
    listing_id: UUID,
    payload: ProductImageReorder,
    principal: Principal = Depends(require_roles("RETAILER")),
    db: Session = Depends(get_db),
) -> list[dict]:
    retailer = _owned_retailer(db, principal.user.id)
    listing = db.scalar(
        select(RetailerProduct)
        .where(RetailerProduct.id == listing_id, RetailerProduct.retailer_id == retailer.id)
        .with_for_update()
    )
    if listing is None:
        raise HTTPException(status_code=404, detail={"code": "listing_not_found", "message": "Product listing was not found."})

    images = db.scalars(
        select(ProductImage)
        .where(ProductImage.product_id == listing.product_id)
        .order_by(ProductImage.sort_order, ProductImage.created_at, ProductImage.id)
        .with_for_update()
    ).all()
    current_ids = {image.id for image in images}
    requested_ids = payload.image_ids
    if set(requested_ids) != current_ids:
        raise HTTPException(
            status_code=422,
            detail={"code": "image_order_mismatch", "message": "image_ids must contain every current product image exactly once."},
        )
    by_id = {image.id: image for image in images}
    for index, image_id in enumerate(requested_ids):
        by_id[image_id].sort_order = index
    db.commit()
    return [
        {
            "id": image.id,
            "url": _public_product_image_url(image),
            "alt_text": image.alt_text,
            "sort_order": image.sort_order,
            "content_type": image.content_type,
            "size_bytes": image.size_bytes,
            "width": image.width,
            "height": image.height,
        }
        for image in sorted(images, key=lambda item: item.sort_order)
    ]


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
    if "original_price_ugx" in changes:
        listing.original_price_ugx = changes["original_price_ugx"]
    if listing.original_price_ugx is not None and listing.original_price_ugx <= listing.price_ugx:
        raise HTTPException(status_code=422, detail={"code": "invalid_discount_price", "message": "Original price must be higher than the current price."})
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
