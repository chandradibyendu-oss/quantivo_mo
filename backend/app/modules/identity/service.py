from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.deps import Principal
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    hash_otp,
    hash_token,
    new_otp_code,
    new_refresh_token,
    otp_matches,
)
from app.modules.audit.service import record
from app.modules.identity.models import OtpChallenge, Role, User, UserRole, UserSession
from app.modules.identity.phone import normalize_indian_mobile
from app.modules.identity.schemas import MeOut, OtpRequestOut, ProfileUpdate, TokenOut
from app.modules.risk.models import RiskProfile

DEFAULT_CAPITAL = "50000.00"
DEFAULT_MAX_RISK = "500.00"
DEFAULT_MAX_QUANTITY = 500
DEFAULT_MAX_EXPOSURE = "200000.00"
DEFAULT_PRODUCTS = ["MIS", "CNC"]


def _token_pair(user: User, session: UserSession, roles: list[str], raw_refresh: str) -> TokenOut:
    settings = get_settings()
    return TokenOut(
        access_token=create_access_token(user_id=user.id, session_id=session.id, roles=roles),
        refresh_token=raw_refresh,
        expires_in_seconds=settings.access_token_ttl_minutes * 60,
        user_id=user.id,
    )


def _rotate_refresh(session: UserSession) -> str:
    raw_refresh = new_refresh_token()
    session.refresh_token_hash = hash_token(raw_refresh)
    return raw_refresh


def _role_names(db: Session, user: User) -> list[str]:
    return list(
        db.scalars(
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
            .order_by(Role.name)
        ).all()
    )


def request_otp(db: Session, phone_raw: str, *, correlation_id: str | None) -> OtpRequestOut:
    settings = get_settings()
    phone = normalize_indian_mobile(phone_raw)
    window_start = utcnow() - timedelta(seconds=settings.otp_request_window_seconds)
    recent = db.scalar(
        select(func.count())
        .select_from(OtpChallenge)
        .where(OtpChallenge.phone_e164 == phone, OtpChallenge.created_at >= window_start)
    )
    if recent >= settings.otp_request_limit:
        raise AppError(429, "rate_limited", "Too many code requests. Wait a few minutes and try again.")

    now = utcnow()
    for challenge in db.scalars(
        select(OtpChallenge).where(OtpChallenge.phone_e164 == phone, OtpChallenge.consumed_at.is_(None))
    ):
        challenge.consumed_at = now

    otp = new_otp_code()
    challenge = OtpChallenge(
        phone_e164=phone,
        code_hash=hash_otp(phone, otp),
        expires_at=now + timedelta(seconds=settings.otp_ttl_seconds),
    )
    db.add(challenge)
    db.flush()
    record(
        db,
        action="auth.otp_requested",
        entity_type="otp_challenge",
        entity_id=challenge.id,
        payload={"phone_e164": phone},
        correlation_id=correlation_id,
    )
    db.commit()
    return OtpRequestOut(
        challenge_id=challenge.id,
        expires_in_seconds=settings.otp_ttl_seconds,
        delivery="dev_mock",
        dev_otp=otp if settings.expose_dev_otp else None,
    )


def _reject_otp(
    db: Session,
    challenge: OtpChallenge,
    *,
    correlation_id: str | None,
    consume: bool = False,
) -> None:
    challenge.attempt_count += 1
    if consume or challenge.attempt_count >= get_settings().otp_max_attempts:
        challenge.consumed_at = utcnow()
    record(
        db,
        action="auth.otp_rejected",
        entity_type="otp_challenge",
        entity_id=challenge.id,
        payload={"phone_e164": challenge.phone_e164, "attempt_count": challenge.attempt_count},
        correlation_id=correlation_id,
    )
    db.commit()
    raise AppError(401, "invalid_otp", "The code is incorrect or has expired.")


def verify_otp(
    db: Session,
    *,
    phone_raw: str,
    challenge_id,
    otp: str,
    device_label: str | None,
    user_agent: str | None,
    correlation_id: str | None,
) -> TokenOut:
    phone = normalize_indian_mobile(phone_raw)
    challenge = db.get(OtpChallenge, challenge_id)
    if challenge is None or challenge.phone_e164 != phone or challenge.consumed_at is not None:
        raise AppError(401, "invalid_otp", "The code is incorrect or has expired.")
    if challenge.expires_at <= utcnow():
        challenge.consumed_at = utcnow()
        db.commit()
        raise AppError(401, "invalid_otp", "The code is incorrect or has expired.")
    if not otp_matches(phone, otp, challenge.code_hash):
        _reject_otp(db, challenge, correlation_id=correlation_id)

    user = db.scalar(select(User).where(User.phone_e164 == phone))
    if user is not None and user.status != "active":
        challenge.consumed_at = utcnow()
        record(
            db,
            action="auth.signin_blocked",
            entity_type="user",
            entity_id=user.id,
            payload={"status": user.status},
            actor_user_id=user.id,
            correlation_id=correlation_id,
        )
        db.commit()
        raise AppError(401, "account_unavailable", "This account cannot sign in.")

    now = utcnow()
    created = False
    if user is None:
        role = db.scalar(select(Role).where(Role.name == "user"))
        if role is None:
            raise AppError(500, "not_configured", "Reference roles are missing. Run python -m app.seed.")
        user = User(phone_e164=phone, status="active", phone_verified_at=now)
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id, granted_at=now))
        from decimal import Decimal

        db.add(
            RiskProfile(
                user_id=user.id,
                capital_allocation_inr=Decimal(DEFAULT_CAPITAL),
                max_risk_inr=Decimal(DEFAULT_MAX_RISK),
                max_quantity=DEFAULT_MAX_QUANTITY,
                max_exposure_inr=Decimal(DEFAULT_MAX_EXPOSURE),
                allowed_products=list(DEFAULT_PRODUCTS),
            )
        )
        created = True
    elif user.phone_verified_at is None:
        user.phone_verified_at = now

    challenge.consumed_at = now
    settings = get_settings()
    session = UserSession(
        user_id=user.id,
        refresh_token_hash="",
        expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        device_label=(device_label or "").strip()[:120] or None,
        user_agent=(user_agent or "").strip()[:255] or None,
        last_seen_at=now,
    )
    raw_refresh = _rotate_refresh(session)
    db.add(session)
    db.flush()
    roles = _role_names(db, user)
    tokens = _token_pair(user, session, roles, raw_refresh)
    record(
        db,
        action="auth.registered" if created else "auth.session_started",
        entity_type="user_session",
        entity_id=session.id,
        payload={"user_id": str(user.id)},
        actor_user_id=user.id,
        correlation_id=correlation_id,
    )
    db.commit()
    return tokens


def refresh_session(db: Session, raw_refresh: str, *, correlation_id: str | None) -> TokenOut:
    session = db.scalar(select(UserSession).where(UserSession.refresh_token_hash == hash_token(raw_refresh)))
    if session is None or session.revoked_at is not None or session.expires_at <= utcnow():
        raise AppError(401, "unauthenticated", "Your session has ended. Sign in again.")
    user = db.get(User, session.user_id)
    if user is None or user.status != "active":
        raise AppError(401, "account_unavailable", "This account cannot sign in.")
    session.last_seen_at = utcnow()
    session.expires_at = utcnow() + timedelta(days=get_settings().refresh_token_ttl_days)
    raw_refresh = _rotate_refresh(session)
    roles = _role_names(db, user)
    tokens = _token_pair(user, session, roles, raw_refresh)
    record(
        db,
        action="auth.session_refreshed",
        entity_type="user_session",
        entity_id=session.id,
        payload={"user_id": str(user.id)},
        actor_user_id=user.id,
        correlation_id=correlation_id,
    )
    db.commit()
    return tokens


def logout(db: Session, principal: Principal, *, correlation_id: str | None) -> None:
    principal.session.revoked_at = utcnow()
    record(
        db,
        action="auth.logout",
        entity_type="user_session",
        entity_id=principal.session.id,
        payload={},
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )
    db.commit()


def to_me(principal: Principal) -> MeOut:
    user = principal.user
    return MeOut(
        id=user.id,
        phone_e164=user.phone_e164,
        display_name=user.display_name,
        status=user.status,
        roles=principal.roles,
    )


def update_profile(db: Session, principal: Principal, body: ProfileUpdate, *, correlation_id: str | None) -> MeOut:
    principal.user.display_name = body.display_name.strip()
    record(
        db,
        action="profile.updated",
        entity_type="user",
        entity_id=principal.user.id,
        payload={"display_name": principal.user.display_name},
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )
    db.commit()
    return to_me(principal)
