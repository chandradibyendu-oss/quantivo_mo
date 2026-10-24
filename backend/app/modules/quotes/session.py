"""One Fyers sign-in covers 15 days. The access token still ends at 6:30 AM IST.

The server mints the next access token from the refresh token and the PIN.
The Fyers password is never collected. Secrets stay out of logs and audit payloads.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from secrets import token_urlsafe
from zoneinfo import ZoneInfo

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.modules.quotes.credentials import clear_fyers_access, save_fyers_access, save_fyers_session

logger = logging.getLogger("quantivo.quotes")

_APP_MISSING = "Save the Fyers app id, app secret, and PIN first."
_SIGN_IN_FAILED = "Fyers did not connect. Return to Admin and sign in again."
_SIGN_IN_PROMPT = (
    "Sign in on Fyers. The server then refreshes the access token each morning for 15 days."
)

IST = ZoneInfo("Asia/Kolkata")
AUTH_URL = "https://api-t1.fyers.in/api/v3/generate-authcode"
VALIDATE_AUTH_URL = "https://api-t1.fyers.in/api/v3/validate-authcode"
VALIDATE_REFRESH_URL = "https://api-t1.fyers.in/api/v3/validate-refresh-token"
_REFRESH_DAYS = 15
_STATE_TTL = timedelta(minutes=10)
_REFRESH_COOLDOWN = timedelta(seconds=60)
_PENDING: dict[str, tuple[datetime, str]] = {}
_LOCK = threading.Lock()
_failed_at: datetime | None = None


@dataclass(frozen=True)
class FyersStatus:
    configured: bool
    app_saved: bool
    connected: bool
    refresh_until: str | None
    detail: str


def _now() -> datetime:
    return datetime.now(IST)


def fyers_status(now: datetime | None = None) -> FyersStatus:
    settings = get_settings()
    moment = now or _now()
    app_saved = _app_saved(settings)
    deadline = _parse(settings.fyers_refresh_until)
    connected = bool(
        settings.fyers_refresh_token.strip() and deadline is not None and moment < deadline
    )
    configured = bool(settings.fyers_quotes_configured and (deadline is None or moment < deadline))
    shown = deadline.astimezone(IST).date().isoformat() if deadline is not None else None
    return FyersStatus(
        configured=configured,
        app_saved=app_saved,
        connected=connected,
        refresh_until=shown if settings.fyers_refresh_token.strip() else None,
        detail=_detail(
            app_saved=app_saved,
            connected=connected,
            deadline=deadline,
            moment=moment,
            has_refresh=bool(settings.fyers_refresh_token.strip()),
        ),
    )


def begin_login(user_id: str, now: datetime | None = None) -> str:
    settings = get_settings()
    if not _app_saved(settings):
        raise AppError(422, "fyers_app_missing", _APP_MISSING)
    moment = now or _now()
    state = token_urlsafe(32)
    with _LOCK:
        _drop_expired(moment)
        _PENDING[state] = (moment + _STATE_TTL, user_id)
    query = urllib.parse.urlencode(
        {
            "client_id": settings.fyers_app_id.strip(),
            "redirect_uri": settings.fyers_redirect_uri.strip(),
            "response_type": "code",
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


def complete_login(
    state: str,
    auth_code: str,
    *,
    post=None,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    moment = now or _now()
    user_id = _consume_state(state.strip(), moment)
    if user_id is None or not _auth_code_ok(auth_code):
        raise AppError(400, "fyers_sign_in_failed", _SIGN_IN_FAILED)
    settings = get_settings()
    if not _app_saved(settings):
        raise AppError(422, "fyers_app_missing", _APP_MISSING)
    payload = {
        "grant_type": "authorization_code",
        "appIdHash": _app_hash(settings),
        "code": auth_code.strip(),
    }
    try:
        body = (post or _post)(VALIDATE_AUTH_URL, payload)
    except (OSError, ValueError):
        logger.warning("Fyers sign-in could not be completed")
        raise AppError(502, "fyers_sign_in_failed", _SIGN_IN_FAILED) from None
    tokens = _token_pair(body)
    if tokens is None:
        logger.warning("Fyers sign-in could not be completed")
        raise AppError(502, "fyers_sign_in_failed", _SIGN_IN_FAILED)
    access_token, refresh_token = tokens
    access_end = access_valid_until(moment)
    refresh_end = moment.astimezone(IST) + timedelta(days=_REFRESH_DAYS)
    save_fyers_session(access_token, refresh_token, access_end.isoformat(), refresh_end.isoformat())
    with _LOCK:
        global _failed_at
        _failed_at = None
    return user_id, refresh_end


def ensure_access_token(*, force: bool = False, post=None, now: datetime | None = None) -> bool:
    """Mint a new access token when the current one has passed 6:30 AM IST."""
    moment = now or _now()
    with _LOCK:
        settings = get_settings()
        if _still_valid(settings, moment, force=force):
            return bool(settings.fyers_access_token.strip())
        global _failed_at
        if _failed_at is not None and moment - _failed_at < _REFRESH_COOLDOWN:
            return False
        if not _can_refresh(settings, moment):
            if settings.fyers_access_token.strip():
                clear_fyers_access()
            return False
        payload = {
            "grant_type": "refresh_token",
            "appIdHash": _app_hash(settings),
            "refresh_token": settings.fyers_refresh_token.strip(),
            "pin": settings.fyers_pin.strip(),
        }
        try:
            body = (post or _post)(VALIDATE_REFRESH_URL, payload)
        except (OSError, ValueError):
            _failed_at = moment
            logger.warning("Fyers access token could not be refreshed")
            return False
        access_token = _access_only(body)
        if access_token is None:
            _failed_at = moment
            logger.warning("Fyers access token could not be refreshed")
            return False
        try:
            save_fyers_access(access_token, access_valid_until(moment).isoformat())
        except AppError:
            _failed_at = moment
            logger.warning("Fyers access token could not be refreshed")
            return False
        _failed_at = None
        return True


def access_valid_until(issued: datetime) -> datetime:
    """The next 6:30 AM IST strictly after the token was issued."""
    local = issued.astimezone(IST)
    boundary = local.replace(hour=6, minute=30, second=0, microsecond=0)
    if local >= boundary:
        boundary += timedelta(days=1)
    return boundary


def _detail(
    *,
    app_saved: bool,
    connected: bool,
    deadline: datetime | None,
    moment: datetime,
    has_refresh: bool,
) -> str:
    if not app_saved:
        return (
            "Save the Fyers app id, app secret, and PIN once. Register the callback URL "
            "on that Fyers app, then sign in on Fyers. Quantivo does not ask for the "
            "Fyers password."
        )
    if has_refresh and deadline is not None and moment >= deadline:
        return f"The Fyers sign-in ended on {_shown(deadline)}. Sign in on Fyers again."
    if connected:
        return (
            f"Connected until {_shown(deadline)}. The access token refreshes after 6:30 AM IST. "
            "Sign in again after that date."
        )
    return _SIGN_IN_PROMPT


def _shown(moment: datetime | None) -> str:
    if moment is None:
        return ""
    local = moment.astimezone(IST)
    return f"{local.day} {local.strftime('%b %Y')}"


def _app_saved(settings: Settings) -> bool:
    return bool(
        settings.fyers_app_id.strip()
        and settings.fyers_app_secret.strip()
        and settings.fyers_pin.strip()
        and settings.fyers_redirect_uri.strip()
    )


def _still_valid(settings: Settings, moment: datetime, *, force: bool) -> bool:
    token = settings.fyers_access_token.strip()
    if not token:
        return False
    if force:
        return False
    until = _parse(settings.fyers_access_until)
    if until is None:
        return True
    return moment < until


def _can_refresh(settings: Settings, moment: datetime) -> bool:
    deadline = _parse(settings.fyers_refresh_until)
    return bool(
        _app_saved(settings)
        and settings.fyers_refresh_token.strip()
        and deadline is not None
        and moment < deadline
    )


def _consume_state(state: str, moment: datetime) -> str | None:
    if not state:
        return None
    with _LOCK:
        _drop_expired(moment)
        found = _PENDING.pop(state, None)
    if found is None or found[0] <= moment:
        return None
    return found[1]


def _drop_expired(moment: datetime) -> None:
    stale = [key for key, (expires, _) in _PENDING.items() if expires <= moment]
    for key in stale:
        _PENDING.pop(key, None)


def _app_hash(settings: Settings) -> str:
    material = f"{settings.fyers_app_id.strip()}:{settings.fyers_app_secret.strip()}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _auth_code_ok(value: str) -> bool:
    cleaned = value.strip()
    return 8 <= len(cleaned) <= 2048 and " " not in cleaned and "\n" not in cleaned


def _token_pair(body: str) -> tuple[str, str] | None:
    payload = _ok_payload(body)
    if payload is None:
        return None
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        return None
    return access_token, refresh_token


def _access_only(body: str) -> str | None:
    payload = _ok_payload(body)
    if payload is None:
        return None
    access_token = payload.get("access_token")
    if not isinstance(access_token, str):
        return None
    return access_token


def _ok_payload(body: str) -> dict | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("s") != "ok":
        return None
    return payload


def _parse(value: str) -> datetime | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed


def _post(url: str, payload: dict) -> str:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Quantivo/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        exc.read()
        raise
