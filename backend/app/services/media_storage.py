"""Provider-neutral product-media validation and storage primitives.

This module deliberately does not upload or proxy remote media. Product images are
currently catalog URLs. The storage protocol and deterministic object-key helper
provide a safe seam for a future authenticated object-storage adapter.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

MAX_PRODUCT_IMAGES = 12
MAX_MEDIA_URL_LENGTH = 1000
ALLOWED_IMAGE_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
ALLOWED_IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_CHARS = set(chr(i) for i in range(32)) | {chr(127)}


class MediaValidationError(ValueError):
    """Raised when product-media metadata violates the WEWE media policy."""


class MediaStorage(Protocol):
    """Minimal object-storage contract for a future provider adapter."""

    def put(self, *, key: str, content: bytes, content_type: str) -> str:
        """Persist bytes and return a stable public/read URL."""

    def delete(self, *, key: str) -> None:
        """Delete an object by its storage key."""


def validate_product_image_url(value: str, *, allowed_hosts: set[str] | None = None) -> str:
    """Validate a catalog image URL without fetching or trusting remote content."""
    value = value.strip()
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
    """Build a deterministic, path-safe object key for future uploads."""
    extension = extension.lower().lstrip(".")
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise MediaValidationError("Unsupported product image extension.")
    if not content:
        raise MediaValidationError("Product image content cannot be empty.")

    digest = hashlib.sha256(content).hexdigest()
    key = PurePosixPath("products") / str(product_id) / f"{digest}.{extension}"
    return str(key)


def validate_uploaded_image_metadata(content_type: str, size_bytes: int, *, max_size_bytes: int) -> None:
    """Validate metadata before an object-storage adapter accepts uploaded bytes."""
    if content_type.lower() not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise MediaValidationError("Only JPEG, PNG, and WebP product images are supported.")
    if size_bytes <= 0 or size_bytes > max_size_bytes:
        raise MediaValidationError("Product image size is outside the configured limit.")
    if max_size_bytes <= 0:
        raise ValueError("max_size_bytes must be positive")
