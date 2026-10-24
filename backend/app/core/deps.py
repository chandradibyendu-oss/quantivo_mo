from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db, utcnow
from app.core.errors import AppError, InvalidToken
from app.core.security import decode_access_token
from app.modules.identity.models import Permission, Role, RolePermission, User, UserRole, UserSession

Db = Annotated[Session, Depends(get_db)]
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user: User
    session: UserSession
    roles: list[str]
    permissions: set[str]


def get_correlation_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


CorrelationId = Annotated[str, Depends(get_correlation_id)]


def _access_for(db: Session, user_id: UUID) -> tuple[list[str], set[str]]:
    role_rows = db.scalars(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
        .order_by(Role.name)
    ).all()
    permission_rows = db.scalars(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
    ).all()
    return list(role_rows), set(permission_rows)


def get_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Db,
) -> Principal:
    if credentials is None:
        raise AppError(401, "unauthenticated", "Sign in to continue.")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = UUID(payload["sub"])
        session_id = UUID(payload["sid"])
    except (InvalidToken, KeyError, ValueError) as exc:
        raise AppError(401, "unauthenticated", "Your session has ended. Sign in again.") from exc

    session = db.get(UserSession, session_id)
    if (
        session is None
        or session.user_id != user_id
        or session.revoked_at is not None
        or session.expires_at <= utcnow()
    ):
        raise AppError(401, "unauthenticated", "Your session has ended. Sign in again.")
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise AppError(401, "account_unavailable", "This account cannot sign in.")
    roles, permissions = _access_for(db, user.id)
    return Principal(user=user, session=session, roles=roles, permissions=permissions)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_permission(code: str):
    def checker(principal: CurrentPrincipal) -> Principal:
        if code not in principal.permissions:
            raise AppError(403, "forbidden", "You do not have access to this action.")
        return principal

    return checker
