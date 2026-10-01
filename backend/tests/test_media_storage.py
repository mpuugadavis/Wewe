from io import BytesIO
from uuid import uuid4

from PIL import Image

import pytest

from app.services.media_storage import (
    MediaValidationError,
    build_product_object_key,
    validate_product_image_url,
    read_upload_with_limit,
    sanitize_image,
    validate_uploaded_image_metadata,
)


def test_product_image_url_requires_https_and_no_credentials_or_fragment() -> None:
    assert validate_product_image_url("https://cdn.example.com/image.webp") == "https://cdn.example.com/image.webp"

    for value in (
        "http://cdn.example.com/image.webp",
        "javascript:alert(1)",
        "https://user:pass@cdn.example.com/image.webp",
        "https://cdn.example.com/image.webp#fragment",
        "https://cdn.example.com/image.webp\n",
    ):
        with pytest.raises(MediaValidationError):
            validate_product_image_url(value)


def test_product_image_url_can_use_an_explicit_host_allowlist() -> None:
    assert validate_product_image_url(
        "https://media.example.com/product.webp",
        allowed_hosts={"media.example.com"},
    )
    with pytest.raises(MediaValidationError):
        validate_product_image_url(
            "https://other.example.com/product.webp",
            allowed_hosts={"media.example.com"},
        )


def test_product_image_url_has_a_bounded_length() -> None:
    with pytest.raises(MediaValidationError):
        validate_product_image_url("https://example.com/" + ("a" * 1000))


def test_product_object_keys_are_deterministic_and_path_safe() -> None:
    product_id = uuid4()
    content = b"test-image"

    key_one = build_product_object_key(product_id, content, ".WEBP")
    key_two = build_product_object_key(product_id, content, "webp")

    assert key_one == key_two
    assert key_one.startswith(f"products/{product_id}/")
    assert key_one.endswith(".webp")
    assert ".." not in key_one


def test_uploaded_image_metadata_is_allow_listed_and_size_limited() -> None:
    validate_uploaded_image_metadata("image/webp", 1024, max_size_bytes=1024)

    for content_type, size in (
        ("application/octet-stream", 100),
        ("image/svg+xml", 100),
        ("image/png", 0),
        ("image/png", 2048),
    ):
        with pytest.raises(MediaValidationError):
            validate_uploaded_image_metadata(content_type, size, max_size_bytes=1024)


def test_invalid_storage_configuration_limit_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_uploaded_image_metadata("image/png", 1, max_size_bytes=0)


def _jpeg_bytes(*, width: int = 32, height: int = 24, with_exif: bool = False) -> bytes:
    image = Image.new("RGB", (width, height), (120, 80, 40))
    output = BytesIO()
    if with_exif:
        exif = Image.Exif()
        exif[274] = 6
        image.save(output, format="JPEG", exif=exif)
    else:
        image.save(output, format="JPEG")
    return output.getvalue()


def test_upload_reader_rejects_oversized_stream_incrementally() -> None:
    with pytest.raises(MediaValidationError):
        read_upload_with_limit(BytesIO(b"x" * 11), max_size_bytes=10)


def test_sanitize_image_checks_real_format_and_strips_metadata() -> None:
    content = _jpeg_bytes(with_exif=True)
    sanitized, content_type, extension, width, height = sanitize_image(
        content,
        declared_content_type="image/jpeg",
        max_size_bytes=1024 * 1024,
    )

    assert content_type == "image/jpeg"
    assert extension == "jpg"
    assert (width, height) == (24, 32)
    with Image.open(BytesIO(sanitized)) as image:
        assert image.getexif() == {}


def test_sanitize_image_rejects_content_type_spoofing() -> None:
    with pytest.raises(MediaValidationError):
        sanitize_image(
            _jpeg_bytes(),
            declared_content_type="image/png",
            max_size_bytes=1024 * 1024,
        )


def test_sanitize_image_rejects_oversized_dimensions() -> None:
    content = _jpeg_bytes(width=8001, height=2)
    with pytest.raises(MediaValidationError):
        sanitize_image(content, declared_content_type="image/jpeg", max_size_bytes=5 * 1024 * 1024)
