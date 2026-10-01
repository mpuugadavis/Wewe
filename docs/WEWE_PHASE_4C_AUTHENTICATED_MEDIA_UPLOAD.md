# WEWE Phase 4C — Authenticated Product Image Uploads

## Purpose

This slice adds the application-side upload path used by retailers without locking WEWE to a single cloud vendor.

The upload boundary is:

1. Authenticated retailer selects a product listing they own.
2. WEWE enforces the 12-image product limit.
3. The multipart body is read incrementally and rejected when it exceeds `MEDIA_MAX_UPLOAD_BYTES`.
4. Pillow verifies the actual file format, not just the filename or browser-supplied MIME type.
5. Only JPEG, PNG and WebP are accepted.
6. Image dimensions are bounded and decompression-bomb protection remains enabled.
7. EXIF orientation is applied and metadata is stripped before storage.
8. WEWE generates the object key; the client never chooses a storage path.
9. The sanitized object is written to S3-compatible object storage.
10. Only after storage succeeds is the `ProductImage` database row committed.
11. If the database commit fails, WEWE attempts to delete the newly stored object.
12. The database stores the storage key, content type, byte size and dimensions alongside the read URL.

## API

`POST /api/v1/retailers/me/products/{listing_id}/images`

Authentication: retailer bearer token.

Multipart fields:

- `file`: image file.
- `alt_text`: optional text, maximum 250 characters.

The endpoint verifies that the authenticated retailer owns the listing and is active and verified.

Uploads return the updated product representation.

## Storage boundary

The implementation uses an S3-compatible adapter. This can be backed by AWS S3 or another compatible object store later. No provider credentials are committed to the repository.

`STORAGE_PROVIDER=DISABLED` is the safe default for local development. When disabled, the upload endpoint returns a controlled `503 media_storage_unavailable` rather than writing files into the application container.

Production requires:

- `STORAGE_PROVIDER=S3`
- `STORAGE_BUCKET`
- `STORAGE_ACCESS_KEY`
- `STORAGE_SECRET_KEY`

`STORAGE_ENDPOINT` may be used for an S3-compatible endpoint, and `STORAGE_PUBLIC_BASE_URL` may be supplied when the storage provider's public/read URL does not follow the default AWS S3 URL shape.

## Object naming

Uploaded objects use:

`products/<product-uuid>/<sha256>.<extension>`

The hash is computed from the sanitized image bytes. This avoids trusting client filenames and makes identical uploads for the same product resolve to the same object key.

## Database metadata

`product_images` now records:

- `url`
- `storage_key`
- `content_type`
- `size_bytes`
- `width`
- `height`
- `sort_order`
- `alt_text`

Legacy URL-only rows remain valid. Their storage metadata stays null.

## Security boundary

The endpoint does not:

- accept SVG or active document formats;
- fetch remote URLs supplied by users;
- trust filename extensions as proof of type;
- trust the browser MIME type without checking the actual image format;
- allow a retailer to upload against another retailer's listing;
- allow arbitrary object keys;
- store uploaded files in the source tree;
- expose storage credentials to the browser.

## Deferred infrastructure work

The repository now contains the application-side upload contract, processing and adapter. The following still require infrastructure/provider selection:

- bucket creation and private/public access policy;
- provider-side encryption and lifecycle rules;
- CDN configuration;
- signed/private delivery URLs if required;
- malware scanning if the chosen threat model requires it;
- orphan-object garbage collection;
- production secret-manager integration;
- frontend retailer upload UI;
- upload progress/resumable uploads for larger files.

The frontend should only expose image upload once a real object-storage environment has been provisioned and tested.
