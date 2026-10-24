"""Attach the admin role to an account that has already signed in.

Usage: python -m app.grant_admin 9845011220
"""

import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_session_factory, utcnow
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.modules.audit.service import record
from app.modules.identity.models import Role, User, UserRole
from app.modules.identity.phone import normalize_indian_mobile


def grant_admin_role(db: Session, phone: str):
    normalized = normalize_indian_mobile(phone)
    user = db.scalar(select(User).where(User.phone_e164 == normalized))
    if user is None:
        raise AppError(
            404,
            "user_not_found",
            "That number has not signed in yet. Sign in once, then grant operator access.",
        )
    role = db.scalar(select(Role).where(Role.name == "admin"))
    if role is None:
        raise AppError(500, "not_configured", "The admin role is missing. Run python -m app.seed.")
    existing = db.scalar(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
    )
    if existing is None:
        db.add(UserRole(user_id=user.id, role_id=role.id, granted_at=utcnow()))
        db.flush()
        record(
            db,
            action="admin.role_granted",
            entity_type="user",
            entity_id=user.id,
            payload={"role": "admin"},
            actor_user_id=None,
            correlation_id="grant-admin",
        )
    return user


def main() -> None:
    configure_logging("INFO")
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m app.grant_admin <indian-mobile>")
    session = get_session_factory()()
    try:
        user = grant_admin_role(session, sys.argv[1])
        session.commit()
    except AppError as exc:
        session.rollback()
        raise SystemExit(exc.message) from exc
    finally:
        session.close()
    print(f"Operator access is on {user.phone_e164}. Sign in again to use the feed settings.")


if __name__ == "__main__":
    main()
