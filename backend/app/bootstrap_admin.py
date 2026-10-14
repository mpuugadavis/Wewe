"""Create the first administrator without sample orders, products or shared passwords."""
import argparse
import getpass
from sqlalchemy import select
from app.models import User
from app.security import hash_password


def create_first_admin(db, email, name, password):
    from email_validator import validate_email
    email = validate_email(email, check_deliverability=False).normalized
    if len(password) < 16:
        raise ValueError("Use an administrator password of at least 16 characters")
    if db.scalar(select(User.id).where(User.role == "ADMIN")):
        raise ValueError("An administrator already exists; use the normal account management flow")
    if db.scalar(select(User.id).where(User.email == email)):
        raise ValueError("This email already belongs to an account")
    user = User(email=email, name=name, password_hash=hash_password(password), role="ADMIN", status="ACTIVE")
    db.add(user)
    db.flush()
    return user


def main():
    from app.db import SessionLocal
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="WEWE administrator")
    args = parser.parse_args()
    password = getpass.getpass("New administrator password (16+ characters): ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match")
    with SessionLocal.begin() as db:
        create_first_admin(db, args.email, args.name, password)
    print("Initial administrator created. No sample data was added.")


if __name__ == "__main__":
    main()
