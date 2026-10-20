"""Restore the public delivery catalogue without seeding users or transactions."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Campus, DeliveryPoint, Hall, University

CURATED_COORDINATES = {'Africa Hall': ('0.337890', '32.568910'),
 'Complex Hall': ('0.329530', '32.569750'),
 'Livingstone Hall': ('0.338770', '32.567990'),
 'Lumumba Hall': ('0.331960', '32.566610'),
 'Mary Stuart Hall': ('0.330580', '32.566590'),
 'Mitchell Hall': ('0.3338875', '32.5705214'),
 'Nkrumah Hall': ('0.335840', '32.569380'),
 'Nsibirwa Hall': ('0.336080', '32.569900'),
 'University Hall': ('0.332897', '32.572208')}

HOSTEL_COORDINATES = {'Makerere International Students Hostel': ('0.334990', '32.560500'),
 'Muhika Hostel': ('0.333190', '32.562550'),
 'JJ Hostel': ('0.337670', '32.561720'),
 'Apex Girls Hostel': ('0.333050', '32.562700'),
 'Makerere Garden Courts': ('0.331290', '32.562080'),
 'Nana Hostel': ('0.325474', '32.566765'),
 'Galloway House': ('0.338690', '32.577920')}

SERVICE_AREAS = {'Kikoni': ('0.335750', '32.562050'),
 'Wandegeya': ('0.331112', '32.573600'),
 'Kagugube': ('0.326810', '32.567820'),
 'Mulago': ('0.342508', '32.576959'),
 'Makerere': ('0.339656', '32.564142')}


def restore_public_locations(db: Session) -> int:
    campus = db.scalar(select(Campus).join(University).where(
        University.slug == "makerere-university", Campus.slug == "main-campus"))
    if campus is None:
        raise ValueError("Makerere main campus must exist before restoring destinations.")
    created = 0
    for kind, coordinates in (("HALL", CURATED_COORDINATES), ("HOSTEL", HOSTEL_COORDINATES), (None, SERVICE_AREAS)):
        for name, (latitude, longitude) in coordinates.items():
            hall = None
            if kind:
                hall = db.scalar(select(Hall).where(Hall.campus_id == campus.id, Hall.name == name))
                if hall is None:
                    hall = Hall(campus_id=campus.id, name=name, kind=kind)
                    db.add(hall)
                    db.flush()
            point = db.scalar(select(DeliveryPoint).where(
                DeliveryPoint.campus_id == campus.id, DeliveryPoint.name == name,
                DeliveryPoint.owner_user_id.is_(None), DeliveryPoint.is_private.is_(False)))
            if point is None:
                point = DeliveryPoint(campus_id=campus.id, name=name,
                    kind="BUILDING" if hall else "OTHER", hall_id=hall.id if hall else None,
                    latitude=latitude, longitude=longitude, is_private=False,
                    directions="Makerere University accommodation" if hall else "Kampala service area")
                db.add(point)
                created += 1
            elif hall and point.hall_id is None:
                point.hall_id = hall.id
            # Preserve administrator coordinates and inactive destinations.
    db.flush()
    return created


def main():
    from app.db import SessionLocal
    with SessionLocal.begin() as db:
        created = restore_public_locations(db)
    print(f"Public locations restored: {created} new destinations; accounts and orders untouched.")


if __name__ == "__main__":
    main()
