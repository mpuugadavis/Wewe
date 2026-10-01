from io import BytesIO

from app.services import media_storage


class FakeS3Client:
    def __init__(self):
        self.uploads = []
        self.deletes = []

    def upload_fileobj(self, content, bucket, key, ExtraArgs):
        self.uploads.append((content.read(), bucket, key, ExtraArgs))

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
