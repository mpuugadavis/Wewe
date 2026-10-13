from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.models import User, Retailer, DeliveryAgent
from app.routers.accounts import upload_delivery_profile_image, upload_retailer_profile_image
from app.services.media_storage import MediaStoragePermissionError


@pytest.mark.parametrize("role", ["RETAILER", "DELIVERY_AGENT"])
def test_profile_upload_read_and_permission_failure_preserves_photo(database, client, monkeypatch, role):
    user = User(id=uuid4(), name="Photo Test", email=f"{uuid4()}@example.test", password_hash="test", role=role, status="ACTIVE")
    database.add(user)
    database.flush()
    if role == "RETAILER":
        database.add(Retailer(user_id=user.id, business_name="Photo Shop", slug=f"shop-{uuid4()}", phone="+256700000091", verification_status="VERIFIED", status="ACTIVE"))
        upload = upload_retailer_profile_image
    else:
        database.add(DeliveryAgent(user_id=user.id, phone="+256700000091", verification_status="PENDING", availability_status="OFFLINE"))
        upload = upload_delivery_profile_image
    database.commit()
    objects = {}
    class Storage:
        fail = False
        def put(self, *, key, content, content_type, size_bytes):
            if self.fail:
                raise MediaStoragePermissionError("denied")
            objects[key] = content.read(), content_type
            return "https://storage.test/" + key
        def get(self, *, key):
            data, mime = objects[key]
            return BytesIO(data), mime, len(data)
        def delete(self, *, key):
            objects.pop(key, None)
    storage = Storage()
    monkeypatch.setattr("app.routers.accounts.build_media_storage", lambda: storage)
    def photo(color):
        stream = BytesIO()
        Image.new("RGB", (48,48), color).save(stream, format="PNG")
        stream.seek(0)
        return UploadFile(file=stream, filename="face.png", headers=Headers({"content-type":"image/png"}))
    result = upload(file=photo("purple"), principal=SimpleNamespace(user=user), db=database)
    assert result["profile_image_url"]
    saved_key = user.profile_image_storage_key
    response = client.get(f"/api/v1/profile-images/{user.id}")
    assert response.status_code == 200
    assert response.content == objects[saved_key][0]
    storage.fail = True
    with pytest.raises(HTTPException) as error:
        upload(file=photo("blue"), principal=SimpleNamespace(user=user), db=database)
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "media_storage_permission_denied"
    database.refresh(user)
    assert user.profile_image_storage_key == saved_key
    assert saved_key in objects
