"""Reset only three additional demo retailers; never alter WEWE's four seed retailers.

Run INSIDE a development/test API container:
  python -m app.reset_extra_demo_retailers          # preview, no writes
  python -m app.reset_extra_demo_retailers --apply  # exactly three .test retailers

New passwords appear in terminal only, after a successful database commit.
Do not redirect output into logs or commit it to Git.
"""

import argparse
import secrets

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Retailer, User
from app.security import hash_password, verify_password

# Protect BOTH email and retailer slug, in case an original seed email changed.
PROTECTED_EMAILS = frozenset({
    "shop@wewe.test",
    "food@wewe.test",
    "creatives@wewe.test",
    "books@wewe.test",
})
PROTECTED_SLUGS = frozenset({
    "thread-theory-ug",
    "nakulabye-kitchen",
    "mug-creatives",
    "campus-bookshop",
})


def is_additional_demo(user: User, retailer: Retailer) -> bool:
    """Exclude original seed shops and any retailer without an explicit .test email."""
    email = (user.email or "").strip().lower()
    slug = (retailer.slug or "").strip().lower()
    return (
        user.role == "RETAILER"
        and email.endswith(".test")
        and "@" in email
        and email not in PROTECTED_EMAILS
        and slug not in PROTECTED_SLUGS
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Reset exactly three eligible demo accounts.")
    args = parser.parse_args()

    settings = get_settings()
    if settings.app_env not in {"development", "test"}:
        raise SystemExit("REFUSED: demo password resets require APP_ENV=development or test.")

    generated: list[tuple[str, str]] = []
    with SessionLocal.begin() as db:
        rows = db.execute(
            select(User, Retailer)
            .join(Retailer, Retailer.user_id == User.id)
            .where(User.role == "RETAILER")
            .order_by(User.email)
            .with_for_update(of=User)
        ).all()
        targets = [(user, retailer) for user, retailer in rows if is_additional_demo(user, retailer)]

        print(f"Additional demo retailer candidates: {len(targets)}")
        for user, retailer in targets:
            print(f"  {retailer.business_name} | {user.email} | {retailer.slug}")

        # Fail CLOSED. Never substitute arbitrary real retailers to make the count three.
        if len(targets) != 3:
            raise SystemExit(
                "REFUSED: expected exactly three non-seed retailers with .test emails. "
                "No passwords were changed. Inspect the actual development database."
            )

        if not args.apply:
            print("PREVIEW ONLY: no passwords changed. Re-run with --apply to reset these three.")
            return

        for user, _retailer in targets:
            password = secrets.token_urlsafe(24)
            user.password_hash = hash_password(password)
            user.token_version += 1  # Invalidate old access/refresh sessions.
            if not verify_password(password, user.password_hash):
                raise RuntimeError("Password verification failed; transaction rolled back.")
            generated.append((user.email, password))

        db.flush()
    # Only expose credentials after the transaction has committed successfully.
    print("\nPASSWORDS RESET FOR EXACTLY THREE ADDITIONAL DEMO RETAILERS")
    for email, password in generated:
        print(f"{email} | {password}")
    print("Save these privately. The four original seed retailers were never changed.")


if __name__ == "__main__":
    main()
