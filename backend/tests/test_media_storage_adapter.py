from io import BytesIO

import pytest
from botocore.exceptions import ClientError

from app.services import media_storage


class FakeS3Client:
    def __init__(self):
        self.uploads = []
        self.deletes = []
        self.objects = {}

    def upload_fileobj(self, content, bucket, key, ExtraArgs):
        payload = content.read()
        self.uploads.append((payload, bucket, key, ExtraArgs))
        self.objects[(bucket, key)] = {
            "Body": BytesIO(payload),
            "ContentType": ExtraArgs["ContentType"],
            "ContentLength": len(payload),
        }

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return self.objects[(Bucket, Key)]

    def delete_object(self, Bucket, Key):
        self.deletes.append((Bucket, Key))


def test_s3_adapter_upload_and_delete(monkeypatch):
    fake = FakeS3Client()
    monkeypatch.setattr(media_storage.boto3, "client", lambda *args, **kwargs: fake)

    storage = media_storage.S3CompatibleMediaStorage(
        bucket="media-bucket",
        access_key="access",
        secret_key="secret",
        endpoint="http://storage.test",
        public_base_url="https://cdn.test/media",
    )

    key = "products/test/image.webp"
    url = storage.put(
        key=key,
        content=BytesIO(b"image-bytes"),
        content_type="image/webp",
        size_bytes=11,
    )
    storage.delete(key=key)

    assert url == "https://cdn.test/media/products/test/image.webp"
    assert fake.uploads == [
        (
            b"image-bytes",
            "media-bucket",
            key,
            {"ContentType": "image/webp", "CacheControl": "public,max-age=31536000,immutable"},
        )
    ]
    assert fake.deletes == [("media-bucket", key)]


def test_s3_adapter_reads_object_and_metadata(monkeypatch):
    fake = FakeS3Client()
    monkeypatch.setattr(media_storage.boto3, "client", lambda *args, **kwargs: fake)
    storage = media_storage.S3CompatibleMediaStorage(
        bucket="media-bucket",
        access_key="access",
        secret_key="secret",
        endpoint="http://storage.test",
        public_base_url="https://cdn.test/media",
    )
    fake.objects[("media-bucket", "products/test/image.webp")] = {
        "Body": BytesIO(b"image-bytes"),
        "ContentType": "image/webp",
        "ContentLength": 11,
    }

    body, content_type, size = storage.get(key="products/test/image.webp")

    assert body.read() == b"image-bytes"
    assert content_type == "image/webp"
    assert size == 11


def test_s3_adapter_reports_missing_object(monkeypatch):
    fake = FakeS3Client()
    monkeypatch.setattr(media_storage.boto3, "client", lambda *args, **kwargs: fake)
    storage = media_storage.S3CompatibleMediaStorage(
        bucket="media-bucket",
        access_key="access",
        secret_key="secret",
        endpoint="http://storage.test",
        public_base_url="https://cdn.test/media",
    )

    with pytest.raises(media_storage.MediaStorageNotFoundError):
        storage.get(key="missing.webp")


def test_product_media_read_serves_cached_image(client, database, monkeypatch):
    from io import BytesIO
    from uuid import uuid4

    from app.models import Category, Product, ProductImage
    from app.routers import catalog

    category = Category(id=uuid4(), name="Test", slug=f"test-{uuid4()}", is_active=True)
    product = Product(id=uuid4(), category_id=category.id, name="Test image", status="ACTIVE")
    image = ProductImage(
        id=uuid4(),
        product_id=product.id,
        url="http://localhost:9000/wewe-media/products/test/image.webp",
        storage_key="products/test/" + "a" * 64 + ".webp",
        content_type="image/webp",
        size_bytes=11,
    )
    database.add_all([category, product, image])
    database.commit()

    class FakeStorage:
        def get(self, *, key):
            assert key == image.storage_key
            return BytesIO(b"image-bytes"), "image/webp", 11

    monkeypatch.setattr(catalog, "build_media_storage", lambda: FakeStorage())

    response = client.get(f"/api/v1/products/images/{image.id}")

    assert response.status_code == 200
    assert response.content == b"image-bytes"
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["etag"] == '"' + "a" * 64 + '"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "cross-origin"


def test_product_media_read_honors_etag(client, database, monkeypatch):
    from io import BytesIO
    from uuid import uuid4

    from app.models import Category, Product, ProductImage
    from app.routers import catalog

    category = Category(id=uuid4(), name="Test", slug=f"test-{uuid4()}", is_active=True)
    product = Product(id=uuid4(), category_id=category.id, name="Test image", status="ACTIVE")
    image = ProductImage(
        id=uuid4(),
        product_id=product.id,
        url="http://localhost:9000/wewe-media/products/test/image.webp",
        storage_key="products/test/" + "b" * 64 + ".webp",
        content_type="image/webp",
        size_bytes=11,
    )
    database.add_all([category, product, image])
    database.commit()

    class FakeStorage:
        def get(self, *, key):
            return BytesIO(b"image-bytes"), "image/webp", 11

    monkeypatch.setattr(catalog, "build_media_storage", lambda: FakeStorage())

    response = client.get(
        f"/api/v1/products/images/{image.id}",
        headers={"If-None-Match": '"' + "b" * 64 + '"'},
    )

    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["etag"] == '"' + "b" * 64 + '"'


def test_product_media_read_rejects_invalid_stored_content_type(client, database, monkeypatch):
    from io import BytesIO
    from uuid import uuid4

    from app.models import Category, Product, ProductImage
    from app.routers import catalog

    category = Category(id=uuid4(), name="Test", slug=f"test-{uuid4()}", is_active=True)
    product = Product(id=uuid4(), category_id=category.id, name="Test image", status="ACTIVE")
    image = ProductImage(
        id=uuid4(),
        product_id=product.id,
        url="http://localhost:9000/wewe-media/products/test/image.webp",
        storage_key="products/test/" + "c" * 64 + ".webp",
        content_type="text/html",
        size_bytes=11,
    )
    database.add_all([category, product, image])
    database.commit()

    class FakeStorage:
        def get(self, *, key):
            return BytesIO(b"<html></html>"), "text/html", 11

    monkeypatch.setattr(catalog, "build_media_storage", lambda: FakeStorage())

    response = client.get(f"/api/v1/products/images/{image.id}")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "invalid_media_metadata"
