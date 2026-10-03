from uuid import UUID
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.limiter import limiter
from app.dependencies import Principal, require_roles
from app.models import Block, Campus, DeliveryPoint, Hall, PickupPoint, University
from app.schemas import LocationCreate, LocationOut

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("/map-tile/{z}/{x}/{y}.png", response_class=Response)
@limiter.limit("120/minute")
def map_tile(z: int, x: int, y: int, request: Request) -> Response:
    """Relay only the tiles visible in the checkout viewport through WEWE.

    This avoids browser-side localhost/referrer edge cases while preserving the
    original browser referrer for OpenStreetMap and identifying WEWE directly.
    It is intentionally bounded to normal Web-Mercator tile coordinates.
    """
    if not (0 <= z <= 19):
        raise HTTPException(status_code=400, detail="Invalid map zoom.")
    limit = 2 ** z
    if not (0 <= x < limit and 0 <= y < limit):
        raise HTTPException(status_code=400, detail="Invalid map tile.")
    upstream_url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    headers = {
        "User-Agent": "WEWE-Campus-Shop/1.0 (+https://github.com/mpuugadavis/Wewe)",
        "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
    }
    referer = request.headers.get("referer")
    if referer:
        headers["Referer"] = referer
    try:
        with urlopen(UrlRequest(upstream_url, headers=headers), timeout=8) as upstream:
            body = upstream.read()
            content_type = upstream.headers.get("Content-Type", "image/png")
            cache_control = upstream.headers.get("Cache-Control", "public, max-age=604800")
            etag = upstream.headers.get("ETag")
    except HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Map tile provider returned HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=502, detail="Map tile provider is temporarily unreachable.") from exc
    response_headers = {
        "Cache-Control": cache_control,
        "X-WEWE-Map-Provider": "OpenStreetMap",
    }
    if etag:
        response_headers["ETag"] = etag
    return Response(content=body, media_type=content_type, headers=response_headers)


@router.get("/maps-config")
def maps_config() -> dict:
    """Return only the browser-restricted Maps key; never expose the server routing key."""
    from app.config import get_settings
    return {"google_maps_api_key": get_settings().google_maps_browser_api_key}


@router.get("/universities")
def universities(db: Session = Depends(get_db)) -> list[dict]:
    return [dict(id=row.id, name=row.name, slug=row.slug, country_code=row.country_code) for row in db.scalars(select(University).where(University.is_active.is_(True)).order_by(University.name)).all()]


@router.get("/campuses")
def campuses(university_id: UUID | None = None, db: Session = Depends(get_db)) -> list[dict]:
    query = select(Campus).where(Campus.is_active.is_(True))
    if university_id:
        query = query.where(Campus.university_id == university_id)
    return [dict(id=row.id, university_id=row.university_id, name=row.name, slug=row.slug) for row in db.scalars(query.order_by(Campus.name)).all()]


@router.get("/halls")
def halls(campus_id: UUID, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Hall).where(Hall.campus_id == campus_id, Hall.is_active.is_(True)).order_by(Hall.name)).all()
    return [dict(id=row.id, campus_id=row.campus_id, name=row.name, kind=row.kind) for row in rows]


@router.get("/blocks")
def blocks(hall_id: UUID, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Block).where(Block.hall_id == hall_id, Block.is_active.is_(True)).order_by(Block.name)).all()
    return [dict(id=row.id, hall_id=row.hall_id, name=row.name) for row in rows]


@router.get("/delivery-points", response_model=list[LocationOut])
def delivery_points(
    campus_id: UUID,
    db: Session = Depends(get_db),
) -> list[DeliveryPoint]:
    query = select(DeliveryPoint).where(
        DeliveryPoint.campus_id == campus_id,
        DeliveryPoint.is_active.is_(True),
        DeliveryPoint.is_private.is_(False),
        DeliveryPoint.kind != "ROOM",
    )
    return list(db.scalars(query.order_by(DeliveryPoint.name)).all())


@router.get("/pickup-points")
def pickup_points(campus_id: UUID | None = None, db: Session = Depends(get_db)) -> list[dict]:
    query = (
        select(PickupPoint, DeliveryPoint)
        .join(DeliveryPoint, DeliveryPoint.id == PickupPoint.delivery_point_id)
        .where(PickupPoint.operating_status == "OPEN", DeliveryPoint.is_active.is_(True))
    )
    if campus_id:
        query = query.where(DeliveryPoint.campus_id == campus_id)
    rows = db.execute(query.order_by(DeliveryPoint.name)).all()
    return [
        {"id": pickup.delivery_point_id, "campus_id": point.campus_id, "name": point.name,
         "directions": point.directions, "opening_hours": pickup.opening_hours}
        for pickup, point in rows
    ]


@router.get("/me/delivery-points", response_model=list[LocationOut])
def my_delivery_points(
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> list[DeliveryPoint]:
    return list(
        db.scalars(
            select(DeliveryPoint)
            .where(DeliveryPoint.owner_user_id == principal.user.id, DeliveryPoint.is_active.is_(True))
            .order_by(DeliveryPoint.created_at.desc())
        ).all()
    )


@router.post("/me/delivery-points", response_model=LocationOut, status_code=status.HTTP_201_CREATED)
def create_my_delivery_point(
    payload: LocationCreate,
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> DeliveryPoint:
    if payload.kind == "PICKUP_POINT":
        raise HTTPException(status_code=422, detail={"code": "invalid_private_location_type", "message": "Customers cannot create official pickup points."})
    validate_hierarchy(db, payload)
    point = DeliveryPoint(
        campus_id=payload.campus_id,
        hall_id=payload.hall_id,
        block_id=payload.block_id,
        owner_user_id=principal.user.id,
        kind=payload.kind,
        name=payload.name.strip(),
        directions=payload.directions,
        latitude=payload.latitude,
        longitude=payload.longitude,
        google_place_id=payload.google_place_id,
        is_private=True,
    )
    db.add(point)
    db.commit()
    db.refresh(point)
    return point


@router.delete("/me/delivery-points/{point_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_delivery_point(
    point_id: UUID,
    principal: Principal = Depends(require_roles("CUSTOMER")),
    db: Session = Depends(get_db),
) -> None:
    point = db.scalar(select(DeliveryPoint).where(DeliveryPoint.id == point_id, DeliveryPoint.owner_user_id == principal.user.id))
    if point is None:
        raise HTTPException(status_code=404, detail={"code": "location_not_found", "message": "Delivery point was not found."})
    point.is_active = False
    db.commit()


def validate_hierarchy(db: Session, payload: LocationCreate) -> None:
    campus = db.get(Campus, payload.campus_id)
    if campus is None or not campus.is_active:
        raise HTTPException(status_code=422, detail={"code": "invalid_campus", "message": "Campus is not active."})
    if payload.hall_id:
        hall = db.get(Hall, payload.hall_id)
        if hall is None or not hall.is_active or hall.campus_id != campus.id:
            raise HTTPException(status_code=422, detail={"code": "invalid_hall", "message": "Hall does not belong to the selected campus."})
    if payload.block_id:
        block = db.get(Block, payload.block_id)
        if block is None or not block.is_active or payload.hall_id != block.hall_id:
            raise HTTPException(status_code=422, detail={"code": "invalid_block", "message": "Block does not belong to the selected hall."})
