from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas import ProductImageReorder


def test_product_image_reorder_requires_unique_ids() -> None:
    image_id = uuid4()
    with pytest.raises(ValidationError):
        ProductImageReorder(image_ids=[image_id, image_id])


def test_product_image_reorder_caps_image_count() -> None:
    with pytest.raises(ValidationError):
        ProductImageReorder(image_ids=[uuid4() for _ in range(13)])


def test_product_image_reorder_accepts_unique_ids() -> None:
    ids = [uuid4(), uuid4(), uuid4()]
    payload = ProductImageReorder(image_ids=ids)
    assert payload.image_ids == ids


def test_private_r2_image_uses_api_media_url_not_private_bucket_hostname() -> None:
    from app.models import ProductImage
    from app.routers.catalog import _public_product_image_url

    image = ProductImage(
        id=uuid4(),
        product_id=uuid4(),
        url="https://unreachable-bucket.s3.amazonaws.com/media/example.webp",
        storage_key=f"products/example/{'a' * 64}.webp",
    )
    assert _public_product_image_url(image) == (
        f"/api/v1/products/images/{image.id}?v={'a' * 64}"
    )


def test_legacy_catalog_url_remains_available() -> None:
    from app.models import ProductImage
    from app.routers.catalog import _public_product_image_url

    url = "https://cdn.example.test/products/legacy.webp"
    image = ProductImage(id=uuid4(), product_id=uuid4(), url=url, storage_key=None)
    assert _public_product_image_url(image) == url
