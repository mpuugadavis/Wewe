"""Rider identification uploads are backed by object storage and need admin reapproval."""

from io import BytesIO
from uuid import uuid4

from PIL import Image
from starlette.datastructures import Headers, UploadFile

from app.models import DeliveryAgent, User
from app.routers import accounts


def test_changing_verified_rider_photo_resets_approval(database, monkeypatch):
    rider = User(
        id=uuid4(),
        name="Photographed Rider",
        email=f"rider-photo-{uuid4()}@example.test",
        password_hash="test-hash",
        role="DELIVERY_AGENT",
        status="ACTIVE",
    )
    rider.profile_image_storage_key = f"profiles/{rider.id}/{'a' * 64}.webp"
    database.add(rider)
    database.flush()
    profile = DeliveryAgent(
        user_id=rider.id,
        phone="+256700000097",
        verification_status="VERIFIED",
        availability_status="AVAILABLE",
        transport_mode="Bicycle",
    )
    database.add(profile)
    database.commit()

    written = []

    class Storage:
        def put(self, *, key, content, content_type, size_bytes):
            body = content.read()
            assert len(body) == size_bytes
            assert content_type == "image/jpeg"
            written.append((key, body))
            return f"https://r2.example.test/{key}"

        def delete(self, *, key):
            pass

    monkeypatch.setattr(accounts, "build_media_storage", lambda: Storage())
    output = BytesIO()
    Image.new("RGB", (32, 32), (140, 60, 100)).save(output, format="JPEG")
    upload = UploadFile(
        file=BytesIO(output.getvalue()),
        filename="rider.jpg",
        headers=Headers({"content-type": "image/jpeg"}),
    )

    accounts._replace_profile_image(rider, upload, database)

    assert written
    assert rider.profile_image_storage_key == written[0][0]
    assert rider.profile_image_url.startswith("/api/v1/profile-images/")
    assert profile.verification_status == "PENDING"
    assert profile.availability_status == "OFFLINE"
