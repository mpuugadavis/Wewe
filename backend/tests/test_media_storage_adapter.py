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
