import os
from io import BytesIO
from uuid import uuid4

import pytest

from app.services.media_storage import S3CompatibleMediaStorage

@pytest.mark.skipif(os.getenv("STORAGE_INTEGRATION") != "1", reason="integration storage not enabled")
def test_s3_compatible_storage_round_trip() -> None:
    bucket = os.environ["STORAGE_BUCKET"]
    storage = S3CompatibleMediaStorage(
        bucket=bucket,
        access_key=os.environ["STORAGE_ACCESS_KEY"],
        secret_key=os.environ["STORAGE_SECRET_KEY"],
        endpoint=os.environ["STORAGE_ENDPOINT"],
        public_base_url=os.environ["STORAGE_PUBLIC_BASE_URL"],
    )
    storage.client.create_bucket(Bucket=bucket)
    key = f"integration-tests/{uuid4()}.webp"
    payload = b"wewe-storage-integration"
    url = storage.put(key=key, content=BytesIO(payload), content_type="image/webp", size_bytes=len(payload))
    assert url == f"{os.environ['STORAGE_PUBLIC_BASE_URL']}/{key}"
    response = storage.client.get_object(Bucket=bucket, Key=key)
    assert response["Body"].read() == payload
    assert response["ContentType"] == "image/webp"
    storage.delete(key=key)
