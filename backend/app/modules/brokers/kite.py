"""A trader signs in on Zerodha. The Kite access token lasts until 06:00 IST.

Zerodha does not issue a refresh token for this app. Logout on Kite ends the session sooner.
The request token from the redirect is exchanged immediately and is not stored.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from secrets import token_urlsafe
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.errors import AppError
from app.modules.brokers.kite_store import read_access_token, save_access_token

logger = logging.getLogger("quantivo.brokers")

IST = ZoneInfo("Asia/Kolkata")
LOGIN_URL = "https://kite.zerodha.com/connect/login"
TOKEN_URL = "https://api.kite.trade/session/token"
_STATE_TTL = timedelta(minutes=10)
_APP_MISSING = "Save the Kite Connect api key and api secret on Admin configuration."
_SIGN_IN_FAILED = "Zerodha did not connect. Return to Account and sign in again."
_SIGN_IN_PROMPT = (
    "Sign in on Zerodha from Account. The session lasts until 6:00 AM IST. "
    "Zerodha does not refresh it. Sign in again after 6:00 AM. This build does not send an order."
)
_EXPIRED = "The Zerodha session ended at 6:00 AM IST. Sign in on Zerodha again."
_DISCONNECTED = (
    "Zerodha is disconnected. Sign in on Zerodha from Account. This build does not send an order."
)
_CLEARED = (
    "The Zerodha app was removed. Sign in again after it is saved. "
    "This build does not send an order."
)
_CLIENT = re.compile(r"^[A-Za-z0-9]{2,16}$")
_REQUEST = re.compile(r"^[A-Za-z0-9]{8,128}$")
_EXCHANGE = re.compile(r"^[A-Z]{2,8}$")
_PENDING: dict[str, tuple[datetime, str]] = {}
_LOCK = threading.Lock()


@dataclass(frozen=True)
class KiteLogin:
    quantivo_user_id: str
    client_id: str
    session_end: datetime
    exchanges: list[str]


@dataclass(frozen=True)
class KiteAccount:
    app_saved: bool
    status: str
    client_id: str | None
    detail: str


def session_end(signed_in_at: datetime) -> datetime:
    """The next 06:00 IST after the sign-in. A sign-in at 06:00 lasts until the next morning."""
    moment = signed_in_at.astimezone(IST)
    end = moment.replace(hour=6, minute=0, second=0, microsecond=0)
    if moment >= end:
        end += timedelta(days=1)
    return end


def app_saved() -> bool:
    settings = get_settings()
    return bool(settings.kite_api_key.strip() and settings.kite_api_secret.strip())


def begin_login(user_id: str, now: datetime | None = None) -> str:
    if not app_saved():
        raise AppError(422, "kite_app_missing", _APP_MISSING)
    moment = now or datetime.now(IST)
    state = token_urlsafe(32)
    with _LOCK:
        _drop_expired(moment)
        _PENDING[state] = (moment + _STATE_TTL, user_id)
    settings = get_settings()
    query = urllib.parse.urlencode(
        {
            "v": "3",
            "api_key": settings.kite_api_key.strip(),
            "redirect_params": urllib.parse.urlencode({"state": state}),
        }
    )
    return f"{LOGIN_URL}?{query}"


def complete_login(
    state: str,
    request_token: str,
    status: str,
    *,
    post=None,
    now: datetime | None = None,
    secret_root=None,
) -> KiteLogin:
    moment = now or datetime.now(IST)
    user_id = _consume_state(state.strip(), moment)
    token_ok = _REQUEST.fullmatch(request_token.strip()) is not None
    if user_id is None or status.strip().lower() != "success" or not token_ok:
        raise AppError(400, "kite_sign_in_failed", _SIGN_IN_FAILED)
    if not app_saved():
        raise AppError(422, "kite_app_missing", _APP_MISSING)
    settings = get_settings()
    api_key = settings.kite_api_key.strip()
    raw = f"{api_key}{request_token.strip()}{settings.kite_api_secret.strip()}"
    checksum = hashlib.sha256(raw.encode()).hexdigest()
    try:
        body = (post or _post)(
            TOKEN_URL,
            {"api_key": api_key, "request_token": request_token.strip(), "checksum": checksum},
        )
    except (OSError, ValueError):
        logger.warning("Zerodha sign-in could not be completed")
        raise AppError(502, "kite_sign_in_failed", _SIGN_IN_FAILED) from None
    parsed = _session(body)
    if parsed is None:
        logger.warning("Zerodha sign-in could not be completed")
        raise AppError(502, "kite_sign_in_failed", _SIGN_IN_FAILED)
    client_id, access_token, exchanges = parsed
    save_access_token(user_id, access_token, secret_root=secret_root)
    return KiteLogin(
        quantivo_user_id=user_id,
        client_id=client_id,
        session_end=session_end(moment),
        exchanges=exchanges,
    )


def end_remote_session(user_id: str, *, delete=None, secret_root=None) -> None:
    token = read_access_token(user_id, secret_root=secret_root)
    settings = get_settings()
    api_key = settings.kite_api_key.strip()
    if token and api_key:
        query = urllib.parse.urlencode({"api_key": api_key, "access_token": token})
        try:
            (delete or _delete)(f"{TOKEN_URL}?{query}")
        except (OSError, ValueError):
            logger.warning("Zerodha sign-out could not be completed")


def describe(
    *,
    app_ready: bool,
    status: str | None,
    client_id: str | None,
    signed_in_at: datetime | None,
    now: datetime,
) -> KiteAccount:
    if not app_ready:
        return KiteAccount(False, "not_set", None, _APP_MISSING)
    if status == "connected" and signed_in_at is not None and client_id:
        end = session_end(signed_in_at)
        if now < end:
            return KiteAccount(True, "connected", client_id, _connected(end, client_id))
        return KiteAccount(True, "expired", client_id, _EXPIRED)
    if status == "expired":
        return KiteAccount(True, "expired", client_id, _EXPIRED)
    return KiteAccount(True, "disconnected", client_id, _DISCONNECTED)


def connected_message(end: datetime, client_id: str) -> str:
    return _connected(end, client_id)


def expired_message() -> str:
    return _EXPIRED


def disconnected_message() -> str:
    return _DISCONNECTED


def cleared_message() -> str:
    return _CLEARED


def _connected(end: datetime, client_id: str) -> str:
    shown = end.astimezone(IST)
    when = f"{shown.day} {shown.strftime('%b %Y')}"
    return (
        f"Connected until 6:00 AM IST on {when}. Client {client_id}. "
        "This build does not send an order."
    )


def _session(body: dict) -> tuple[str, str, list[str]] | None:
    if body.get("status") != "success" or not isinstance(body.get("data"), dict):
        return None
    data = body["data"]
    client_id = str(data.get("user_id", "")).strip().upper()
    access_token = str(data.get("access_token", "")).strip()
    raw_exchanges = data.get("exchanges")
    exchanges = []
    if isinstance(raw_exchanges, list):
        for item in raw_exchanges:
            code = str(item).strip().upper()
            if _EXCHANGE.fullmatch(code) and code not in exchanges:
                exchanges.append(code)
            if len(exchanges) == 16:
                break
    if _CLIENT.fullmatch(client_id) is None or not access_token:
        return None
    return client_id, access_token, exchanges or ["NSE"]


def _consume_state(state: str, moment: datetime) -> str | None:
    with _LOCK:
        _drop_expired(moment)
        pending = _PENDING.pop(state, None)
    if pending is None or moment > pending[0]:
        return None
    return pending[1]


def _drop_expired(moment: datetime) -> None:
    stale = [key for key, (deadline, _user) in _PENDING.items() if moment > deadline]
    for key in stale:
        _PENDING.pop(key, None)


def _post(url: str, form: dict[str, str]) -> dict:
    data = urllib.parse.urlencode(form).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"X-Kite-Version": "3", "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        error.read()
        raise ValueError("kite token exchange failed") from None
    if not isinstance(payload, dict):
        raise ValueError("kite token exchange failed")
    return payload


def _delete(url: str) -> None:
    request = urllib.request.Request(url, method="DELETE", headers={"X-Kite-Version": "3"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()
    except urllib.error.HTTPError as error:
        error.read()
        raise ValueError("kite sign-out failed") from None
