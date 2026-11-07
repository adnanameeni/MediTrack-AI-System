"""Gives (or removes) administrator rights for a user who has already signed up.

  python -m scripts.make_admin someone@example.com
  python -m scripts.make_admin someone@example.com --revoke

There is no public admin signup. This command is the only way to create the
first administrator. No password is typed or stored here.
"""

import argparse
import sys

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.admin_audit import ACTION_ROLE_CHANGED, AdminAuditLog
from app.models.user import ROLE_ADMIN, ROLE_USER, User


class LastAdminError(Exception):
    """Raised when removing the only active administrator."""


def set_role(db: Session, email: str, role: str) -> User | None:
    """Set a user's role. Returns None if no user has that email."""
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        return None
    if user.role == role:
        return user

    if user.role == ROLE_ADMIN and user.is_active:
        other_active_admins = db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == ROLE_ADMIN, User.is_active.is_(True), User.id != user.id)
        )
        if other_active_admins == 0:
            raise LastAdminError

    previous = user.role
    user.role = role
    db.add(
        AdminAuditLog(
            admin_user_id=None,
            target_user_id=user.id,
            action=ACTION_ROLE_CHANGED,
            detail=f"{previous} -> {role} (command line)",
        )
    )
    db.commit()
    return user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Give or remove administrator rights.")
    parser.add_argument("email", help="Email of an existing user")
    parser.add_argument("--revoke", action="store_true", help="Make the user a normal user again")
    args = parser.parse_args(argv)

    role = ROLE_USER if args.revoke else ROLE_ADMIN
    db = SessionLocal()
    try:
        user = set_role(db, args.email, role)
        user_email = user.email if user is not None else None
    except LastAdminError:
        print("Refused: this is the only active administrator. Make another admin first.")
        return 1
    except OperationalError:
        db.rollback()
        print(
            "The database is not ready. Run these first:\n"
            "  python -m scripts.add_role_column\n"
            "  python -m scripts.create_tables"
        )
        return 1
    finally:
        db.close()

    if user_email is None:
        print("No user with that email. Sign up in the app first, then run this again.")
        return 1
    if role == ROLE_ADMIN:
        print(f"{user_email} is now an administrator.")
    else:
        print(f"{user_email} is now a normal user.")
    return 0


if __name__ == "__main__":
    sys.exit(main())