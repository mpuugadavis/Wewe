"""Secure product-media validation, processing, and object-storage primitives.

Remote catalog URLs remain supported for backwards compatibility. Authenticated
uploads use validated image bytes and an S3-compatible object-storage adapter.
The application never fetches arbitrary remote catalog URLs.
"""

from __future__ import annotations

import hashlib
import io
import warnings
from pathlib import PurePosixPath
from datetime import datetime
from typing import BinaryIO, Protocol
from urllib.parse import urlsplit
from uuid import UUID

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PRODUCT_IMAGES = 12
MAX_MEDIA_URL_LENGTH = 1000
ALLOWED_IMAGE_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
ALLOWED_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp"})
MAX_IMAGE_DIMENSION = 8000
MAX_IMAGE_PIXELS = 25_000_000
_CONTROL_CHARS = set(chr(i) for i in range(32)) | {chr(127)}


class MediaValidationError(ValueError):
    """Raised when product-media policy is violated."""


class MediaStorageError(RuntimeError):
    """Raised when object storage cannot complete an operation."""


class MediaStorageNotFoundError(MediaStorageError):
    """Raised when an object does not exist in object storage."""


class MediaStorage(Protocol):
    def put(self, *, key: str, content: BinaryIO, content_type: str, size_bytes: int) -> str:
        """Persist a stream and return its stable read URL."""

    def get(self, *, key: str) -> tuple[BinaryIO, str | None, int | None]:
        """Read an object and return its body, content type, and size."""

    def presign_get(self, *, key: str, expires_in: int) -> str:
        """Create a short-lived signed URL for reading an object."""

    def list_objects(self, *, prefix: str) -> list[tuple[str, datetime | None]]:
        """List object keys and modification times under a storage prefix."""

    def delete(self, *, key: str) -> None:
        """Delete an object by storage key."""

    def healthcheck(self) -> None:
        """Verify bucket reachability without reading or mutating objects."""


class S3CompatibleMediaStorage:
    """S3-compatible object storage adapter (AWS S3, R2, MinIO, etc.)."""

    def __init__(
        self,
        *,
        bucket: str,
        access_key: str,
        secret_key: str,
        endpoint: str | None,
        public_base_url: str | None,
    ) -> None:
        if not bucket or not access_key or not secret_key:
            raise ValueError("Object storage bucket and credentials are required.")
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/") if public_base_url else None
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def put(self, *, key: str, content: BinaryIO, content_type: str, size_bytes: int) -> str:
        try:
            self.client.upload_fileobj(
                content,
                self.bucket,
                key,
                ExtraArgs={
                    "ContentType": content_type,
                    "CacheControl": "public,max-age=31536000,immutable",
                },
            )
        except (BotoCoreError, ClientError) as exc:
            raise MediaStorageError("Object storage upload failed.") from exc
        if self.public_base_url:
            return f"{self.public_base_url}/{key}"
        return f"https://{self.bucket}.s3.amazonaws.com/{key}"

    def get(self, *, key: str) -> tuple[BinaryIO, str | None, int | None]:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"], response.get("ContentType"), response.get("ContentLength")
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise MediaStorageNotFoundError("Object was not found in object storage.") from exc
            raise MediaStorageError("Object storage read failed.") from exc
        except BotoCoreError as exc:
            raise MediaStorageError("Object storage read failed.") from exc

    def presign_get(self, *, key: str, expires_in: int) -> str:
        if expires_in <= 0 or expires_in > 3600:
            raise ValueError("expires_in must be between 1 and 3600 seconds")
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except (BotoCoreError, ClientError) as exc:
            raise MediaStorageError("Object storage signed URL generation failed.") from exc

    def list_objects(self, *, prefix: str) -> list[tuple[str, datetime | None]]:
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            objects: list[tuple[str, datetime | None]] = []
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    key = item.get("Key")
                    if key:
                        objects.append((key, item.get("LastModified")))
            return objects
        except (BotoCoreError, ClientError) as exc:
            raise MediaStorageError("Object storage listing failed.") from exc

    def delete(self, *, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise MediaStorageError("Object storage deletion failed.") from exc

    def healthcheck(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except (BotoCoreError, ClientError) as exc:
            raise MediaStorageError("Object storage health check failed.") from exc


def validate_product_image_url(value: str, *, allowed_hosts: set[str] | None = None) -> str:
    """Validate a catalog image URL without fetching or trusting remote content."""
    if value != value.strip():
        raise MediaValidationError("Product image URL must not have leading or trailing whitespace.")
    if not value or len(value) > MAX_MEDIA_URL_LENGTH:
        raise MediaValidationError(f"Product image URL must be 1-{MAX_MEDIA_URL_LENGTH} characters.")
    if any(char in _CONTROL_CHARS for char in value) or any(char.isspace() for char in value):
        raise MediaValidationError("Product image URL must not contain whitespace or control characters.")

    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise MediaValidationError("Product images must use an HTTPS URL.")
    if parsed.username is not None or parsed.password is not None:
        raise MediaValidationError("Product image URLs must not contain credentials.")
    if parsed.fragment:
        raise MediaValidationError("Product image URLs must not contain URL fragments.")

    hostname = parsed.hostname.rstrip(".").lower()
    if allowed_hosts and hostname not in {host.rstrip(".").lower() for host in allowed_hosts}:
        raise MediaValidationError("Product image host is not allow-listed.")
    return value


def build_product_object_key(product_id: UUID, content: bytes, extension: str) -> str:
    extension = extension.lower().lstrip(".")
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise MediaValidationError("Unsupported product image extension.")
    if not content:
        raise MediaValidationError("Product image content cannot be empty.")
    digest = hashlib.sha256(content).hexdigest()
    return str(PurePosixPath("products") / str(product_id) / f"{digest}.{extension}")


def build_profile_object_key(user_id: UUID, content: bytes, extension: str) -> str:
    extension = extension.lower().lstrip(".")
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise MediaValidationError("Unsupported profile image extension.")
    if not content:
        raise MediaValidationError("Profile image content cannot be empty.")
    digest = hashlib.sha256(content).hexdigest()
    return str(PurePosixPath("profiles") / str(user_id) / f"{digest}.{extension}")


def validate_uploaded_image_metadata(content_type: str, size_bytes: int, *, max_size_bytes: int) -> None:
    if max_size_bytes <= 0:
        raise ValueError("max_size_bytes must be positive")
    if content_type.lower() not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise MediaValidationError("Only JPEG, PNG, and WebP product images are supported.")
    if size_bytes <= 0 or size_bytes > max_size_bytes:
        raise MediaValidationError("Product image size is outside the configured limit.")


def read_upload_with_limit(stream: BinaryIO, *, max_size_bytes: int) -> bytes:
    """Read incrementally so oversized multipart bodies are rejected before buffering."""
    if max_size_bytes <= 0:
        raise ValueError("max_size_bytes must be positive")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(1024 * 1024, max_size_bytes + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > max_size_bytes:
            raise MediaValidationError("Product image exceeds the configured size limit.")
        chunks.append(chunk)
    if total == 0:
        raise MediaValidationError("Product image cannot be empty.")
    return b"".join(chunks)


def sanitize_image(content: bytes, *, declared_content_type: str, max_size_bytes: int) -> tuple[bytes, str, str, int, int]:
    """Verify actual image format, reject unsafe dimensions, apply EXIF orientation, and strip metadata."""
    validate_uploaded_image_metadata(declared_content_type, len(content), max_size_bytes=max_size_bytes)
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                actual_format = (image.format or "").upper()
                expected_format = {
                    "image/jpeg": "JPEG",
                    "image/png": "PNG",
                    "image/webp": "WEBP",
                }[declared_content_type.lower()]
                if actual_format != expected_format:
                    raise MediaValidationError("Uploaded bytes do not match the declared image content type.")
                image.verify()

            with Image.open(io.BytesIO(content)) as image:
                if (
                    image.width <= 0
                    or image.height <= 0
                    or image.width > MAX_IMAGE_DIMENSION
                    or image.height > MAX_IMAGE_DIMENSION
                ):
                    raise MediaValidationError("Image dimensions are outside the supported range.")
                image = ImageOps.exif_transpose(image)
                image.load()
                width, height = image.size
                if actual_format == "JPEG":
                    if image.mode not in ("RGB", "L"):
                        image = image.convert("RGB")
                    output_type, extension = "image/jpeg", "jpg"
                    save_kwargs = {"format": "JPEG", "quality": 90, "optimize": True}
                elif actual_format == "PNG":
                    output_type, extension = "image/png", "png"
                    save_kwargs = {"format": "PNG", "optimize": True}
                else:
                    if image.mode not in ("RGB", "RGBA"):
                        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                    output_type, extension = "image/webp", "webp"
                    save_kwargs = {"format": "WEBP", "quality": 90, "method": 4}
                output = io.BytesIO()
                image.save(output, **save_kwargs)
                sanitized = output.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError, OSError, ValueError) as exc:
        if isinstance(exc, MediaValidationError):
            raise
        raise MediaValidationError("Uploaded file is not a valid supported image.") from exc

    if len(sanitized) > max_size_bytes:
        raise MediaValidationError("Processed image exceeds the configured size limit.")
    return sanitized, output_type, extension, width, height
