"""The Fyers access token ends at 6:30 AM IST.

When a TOTP key is saved, the server signs in after that time. The Fyers password
is never collected. Secrets stay out of logs and audit payloads.
"""

from __future__ import annotations

import base64
import hashlib
import http.cookiejar
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
from app.modules.quotes.totp import totp_code

logger = logging.getLogger("quantivo.quotes")

_APP_MISSING = "Save the Fyers app id, app secret, and PIN first."
_SIGN_IN_FAILED = "Fyers did not connect. Return to Admin and sign in again."
_SIGN_IN_PROMPT = (
    "Sign in on Fyers, or save the Fyers client id and TOTP key. "
    "The access token ends at 6:30 AM IST."
)

IST = ZoneInfo("Asia/Kolkata")
AUTH_URL = "https://api-t1.fyers.in/api/v3/generate-authcode"
VALIDATE_AUTH_URL = "https://api-t1.fyers.in/api/v3/validate-authcode"
VALIDATE_REFRESH_URL = "https://api-t1.fyers.in/api/v3/validate-refresh-token"
SEND_OTP_URL = "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
VERIFY_OTP_URL = "https://api-t2.fyers.in/vagator/v2/verify_otp"
VERIFY_PIN_URL = "https://api-t2.fyers.in/vagator/v2/verify_pin_v2"
APP_TOKEN_URL = "https://api-t1.fyers.in/api/v3/token"
_REFRESH_DAYS = 15
_STATE_TTL = timedelta(minutes=10)
_REFRESH_COOLDOWN = timedelta(seconds=60)
_TOTP_COOLDOWN = timedelta(minutes=15)
_PENDING: dict[str, tuple[datetime, str]] = {}
_LOCK = threading.Lock()
_failed_at: datetime | None = None
_totp_failed_at: datetime | None = None


@dataclass(frozen=True)
class FyersStatus:
    configured: bool
    app_saved: bool
    connected: bool
    app_id: str
    client_id: str
    totp_saved: bool
    refresh_until: str | None
    detail: str


def _now() -> datetime:
    return datetime.now(IST)


def fyers_status(now: datetime | None = None) -> FyersStatus:
    settings = get_settings()
    moment = now or _now()
    app_saved = _app_saved(settings)
    deadline = _parse(settings.fyers_refresh_until)
    access_end = _parse(settings.fyers_access_until)
    connected = _still_valid(settings, moment, force=False)
    totp_saved = _can_totp(settings)
    configured = bool(settings.fyers_quotes_configured or totp_saved)
    shown = deadline.astimezone(IST).date().isoformat() if deadline is not None else None
    return FyersStatus(
        configured=configured,
        app_saved=app_saved,
        connected=connected,
        app_id=settings.fyers_app_id.strip(),
        client_id=settings.fyers_client_id.strip(),
        totp_saved=totp_saved,
        refresh_until=shown if settings.fyers_refresh_token.strip() else None,
        detail=_detail(
            app_saved=app_saved,
            connected=connected,
            totp_saved=totp_saved,
            access_end=access_end,
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


def ensure_access_token(
    *,
    force: bool = False,
    post=None,
    login=None,
    now: datetime | None = None,
) -> bool:
    """Mint a new access token when the current one has passed 6:30 AM IST."""
    moment = now or _now()
    with _LOCK:
        settings = get_settings()
        if _still_valid(settings, moment, force=force):
            return bool(settings.fyers_access_token.strip())
        if _can_totp(settings):
            return _mint_with_totp(settings, moment, login)
        return _mint_with_refresh(settings, moment, post)


def access_valid_until(issued: datetime) -> datetime:
    """The next 6:30 AM IST strictly after the token was issued."""
    local = issued.astimezone(IST)
    boundary = local.replace(hour=6, minute=30, second=0, microsecond=0)
    if local >= boundary:
        boundary += timedelta(days=1)
    return boundary


def _mint_with_totp(settings: Settings, moment: datetime, login) -> bool:
    global _totp_failed_at
    if _totp_failed_at is not None and moment - _totp_failed_at < _TOTP_COOLDOWN:
        return False
    try:
        access_token = (login or login_with_totp)(settings, now=moment)
    except (OSError, ValueError):
        _totp_failed_at = moment
        logger.warning("Fyers TOTP sign-in could not be completed")
        return False
    if access_token is None:
        _totp_failed_at = moment
        logger.warning("Fyers TOTP sign-in could not be completed")
        return False
    try:
        save_fyers_access(access_token, access_valid_until(moment).isoformat())
    except AppError:
        _totp_failed_at = moment
        logger.warning("Fyers TOTP sign-in could not be completed")
        return False
    _totp_failed_at = None
    return True


def _mint_with_refresh(settings: Settings, moment: datetime, post) -> bool:
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
        _log_fyers(body)
        return False
    try:
        save_fyers_access(access_token, access_valid_until(moment).isoformat())
    except AppError:
        _failed_at = moment
        logger.warning("Fyers access token could not be refreshed")
        return False
    _failed_at = None
    return True


def login_with_totp(settings: Settings, *, now: datetime) -> str | None:
    """Sign in with the saved client id, TOTP key, and PIN. Returns the access token."""

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect())
    client_id = settings.fyers_client_id.strip().upper()
    first = _send(opener, SEND_OTP_URL, {"fy_id": _b64(client_id), "app_id": "2"})
    request_key = _field(first, "request_key")
    if request_key is None:
        return None
    second = _send(
        opener,
        VERIFY_OTP_URL,
        {"request_key": request_key, "otp": totp_code(settings.fyers_totp_secret, now)},
    )
    request_key = _field(second, "request_key")
    if request_key is None:
        return None
    third = _send(
        opener,
        VERIFY_PIN_URL,
        {
            "request_key": request_key,
            "identity_type": "pin",
            "identifier": _b64(settings.fyers_pin.strip()),
        },
    )
    session_token = _nested(third, "access_token")
    if session_token is None:
        return None
    app_id, app_type = _app_parts(settings.fyers_app_id)
    issued = _send(
        opener,
        APP_TOKEN_URL,
        {
            "fyers_id": client_id,
            "app_id": app_id,
            "redirect_uri": settings.fyers_redirect_uri.strip(),
            "appType": app_type,
            "code_challenge": "",
            "state": "quantivo",
            "scope": "",
            "nonce": "",
            "response_type": "code",
            "create_cookie": True,
        },
        {"Authorization": f"Bearer {session_token}"},
    )
    auth_code = _auth_from_redirect(issued)
    if auth_code is None:
        return None
    exchanged = _send(
        opener,
        VALIDATE_AUTH_URL,
        {
            "grant_type": "authorization_code",
            "appIdHash": _app_hash(settings),
            "code": auth_code,
        },
    )
    return _access_only(exchanged)


def _detail(
    *,
    app_saved: bool,
    connected: bool,
    totp_saved: bool,
    access_end: datetime | None,
) -> str:
    if not app_saved:
        return (
            "Save the Fyers app id, app secret, PIN, client id, and TOTP key once. "
            "The server signs in after 6:30 AM IST. Quantivo does not ask for the Fyers password."
        )
    if connected:
        follow = (
            "The server signs in again after that."
            if totp_saved
            else "Save the Fyers client id and TOTP key so the server can sign in again after that."
        )
        return f"Connected until 6:30 AM IST on {_shown(access_end)}. {follow}"
    if totp_saved:
        return (
            "The Fyers access token ended at 6:30 AM IST. "
            "The server signs in with the saved TOTP key on the next price read."
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


def _can_totp(settings: Settings) -> bool:
    return bool(
        _app_saved(settings)
        and settings.fyers_client_id.strip()
        and settings.fyers_totp_secret.strip()
    )


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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _send(opener, url: str, payload: dict, headers: dict[str, str] | None = None) -> str:
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Quantivo/1.0",
    }
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with opener.open(request, timeout=15) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if 300 <= exc.code < 400:
            if _object(body) is None:
                location = exc.headers.get("Location") or ""
                if location:
                    return json.dumps({"Url": location})
            return body
        _log_fyers(body)
        raise


def _field(body: str, name: str) -> str | None:
    payload = _object(body)
    value = None if payload is None else payload.get(name)
    if not isinstance(value, str) or not value.strip():
        data = None if payload is None else payload.get("data")
        value = data.get(name) if isinstance(data, dict) else None
    if isinstance(value, str) and value.strip():
        return value
    _log_fyers(body)
    return None


def _nested(body: str, name: str) -> str | None:
    payload = _object(body)
    data = None if payload is None else payload.get("data")
    value = data.get(name) if isinstance(data, dict) else None
    if isinstance(value, str) and value.strip():
        return value
    _log_fyers(body)
    return None


def _auth_from_redirect(body: str) -> str | None:
    payload = _object(body)
    raw = ""
    if payload is not None:
        candidate = payload.get("Url") or payload.get("url") or ""
        raw = candidate if isinstance(candidate, str) else ""
    parsed = urllib.parse.urlparse(raw)
    found = urllib.parse.parse_qs(parsed.query).get("auth_code", [])
    if found and _auth_code_ok(found[0]):
        return found[0]
    _log_fyers(body)
    return None


def _app_parts(app_id: str) -> tuple[str, str]:
    cleaned = app_id.strip()
    if "-" in cleaned:
        head, tail = cleaned.rsplit("-", 1)
        if head and tail.isdigit():
            return head, tail
    return cleaned, "100"


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _object(body: str) -> dict | None:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _log_fyers(body: str) -> None:
    payload = _object(body)
    if payload is None:
        logger.warning("Fyers sign-in was refused")
        return
    code = payload.get("code")
    message = payload.get("message") if isinstance(payload.get("message"), str) else ""
    logger.warning("Fyers sign-in was refused code=%s message=%s", code, message[:180])


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
