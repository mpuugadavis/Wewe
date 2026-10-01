# WEWE Phase 4C — Product Media and Storage Hardening

## Current media boundary

WEWE currently accepts catalog image URLs, not arbitrary uploaded files. Product creation accepts HTTPS image URLs only; the API does not download, proxy, transform, or execute remote media.

This is intentional. A cloud storage provider is not selected yet, and no provider-specific SDK or sandbox adapter is introduced by this phase.

## Implemented hardening

- Product image URLs are limited to 12 per product and 1,000 characters each.
- URLs must use HTTPS.
- URLs cannot contain credentials, fragments, whitespace, or control characters.
- Duplicate image URLs for the same product are rejected.
- An optional exact host allow-list is available through MEDIA_ALLOWED_HOSTS.
- The database enforces HTTPS URLs, non-negative image ordering, and unique (product_id, url) pairs.
- Future uploaded media is constrained to JPEG, PNG, or WebP and a configurable byte limit (MEDIA_MAX_UPLOAD_BYTES, default 5 MiB).
- Future object keys are generated from a product UUID plus a SHA-256 content digest; caller-controlled filenames are never used as storage paths.
- A provider-neutral MediaStorage protocol defines the future upload/delete seam without selecting a cloud provider.

## Important security boundary

The API deliberately does not fetch remote image URLs to inspect their content. Fetching arbitrary retailer-supplied URLs would create an SSRF surface and would make remote content availability part of product creation.

URL validation is therefore metadata validation only. When authenticated uploads are introduced, the storage adapter must validate the actual bytes before persistence.

At minimum, the future upload flow must:

1. Require an authenticated, verified retailer with ownership of the product/listing.
2. Enforce the configured byte limit before buffering the entire request.
3. Allow only JPEG, PNG, and WebP.
4. Detect the actual file type from bytes rather than trusting the filename or Content-Type header.
5. Reject SVG and other active/document formats.
6. Validate image dimensions and protect against decompression bombs.
7. Strip EXIF metadata where practical, especially GPS/location metadata.
8. Generate server-controlled object keys; never use the original filename as a path.
9. Store objects outside the application source tree and database.
10. Persist the database record only after successful object storage, with cleanup on transaction failure.
11. Delete or replace old objects safely when product media is removed.
12. Use private buckets plus signed/read-controlled URLs where the selected provider supports them.
13. Apply provider-side encryption, lifecycle, access logging, and least-privilege credentials.
14. Keep provider credentials in the deployment secret store, never in the repository.

## Configuration

- MEDIA_ALLOWED_HOSTS — comma-separated exact host names permitted for URL-based catalog images. Empty means any HTTPS host.
- MEDIA_MAX_UPLOAD_BYTES — maximum future uploaded object size; default 5 MiB.
- STORAGE_BUCKET, STORAGE_ENDPOINT, STORAGE_ACCESS_KEY, and STORAGE_SECRET_KEY remain provider-neutral placeholders.

No storage provider is assumed by the application.

## Deferred work

The following is intentionally deferred until the storage provider and deployment architecture are selected:

- authenticated multipart upload endpoint
- object-storage SDK/adapter
- signed URL generation
- image byte decoding and thumbnail generation
- orphan-object garbage collection
- CDN integration
- provider-specific bucket policies

This keeps the current URL-only catalog path working while preventing an unsafe local-filesystem upload implementation from being mistaken for production object storage.
