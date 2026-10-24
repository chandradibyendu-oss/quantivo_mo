import hashlib
import hmac
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

import jwt

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.errors import InvalidToken


def hash_otp(phone_e164: str, otp: str) -> str:
    settings = get_settings()
    digest = hmac.new(
        settings.secret_key.encode(),
        f"{phone_e164}:{otp}".encode(),
        hashlib.sha256,
    )
    return digest.hexdigest()


def otp_matches(phone_e164: str, otp: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(phone_e164, otp), code_hash)


def new_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_access_token(*, user_id: UUID, session_id: UUID, roles: list[str]) -> str:
    settings = get_settings()
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "roles": roles,
        "typ": "access",
        "jti": uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise InvalidToken from exc
    if payload.get("typ") != "access":
        raise InvalidToken
    return payload
