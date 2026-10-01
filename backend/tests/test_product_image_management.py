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
