"""Fyers quote secrets live in the server environment, not in a table.

The file holds the app id, app secret, PIN, client id, TOTP key, access token, and refresh token.
None of those values are written to a log or an audit payload.
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.core.errors import AppError
from app.modules.progress.history import clear_history_cache
from app.modules.quotes.fyers import clear_quote_cache

ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
_KEYS = (
    "FYERS_APP_ID",
    "FYERS_APP_SECRET",
    "FYERS_PIN",
    "FYERS_CLIENT_ID",
    "FYERS_TOTP_SECRET",
    "FYERS_ACCESS_TOKEN",
    "FYERS_REFRESH_TOKEN",
    "FYERS_ACCESS_UNTIL",
    "FYERS_REFRESH_UNTIL",
    "FYERS_REDIRECT_URI",
)
_APP_ID = re.compile(r"^[A-Za-z0-9-]{4,64}$")
_SECRET = re.compile(r"^[A-Za-z0-9._~+/=-]{8,256}$")
_PIN = re.compile(r"^\d{4}$")
_CLIENT = re.compile(r"^[A-Z0-9]{2,16}$")
_TOTP = re.compile(r"^[A-Z2-7]{16,64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9._~+/=-]{20,4096}$")
_CALLBACK_PATH = "/api/v1/admin/fyers/callback"
_LOCK = threading.Lock()


def save_fyers_app(
    app_id: str,
    app_secret: str,
    pin: str,
    redirect_uri: str,
    *,
    client_id: str = "",
    totp_key: str = "",
    env_file: Path | None = None,
    apply: bool = True,
) -> None:
    path = ENV_PATH if env_file is None else env_file
    cleaned_id = app_id.strip() or (_stored(path, "FYERS_APP_ID") or "")
    cleaned_secret = app_secret.strip() or (_stored(path, "FYERS_APP_SECRET") or "")
    cleaned_pin = pin.strip() or (_stored(path, "FYERS_PIN") or "")
    cleaned_redirect = redirect_uri.strip() or (_stored(path, "FYERS_REDIRECT_URI") or "")
    if _APP_ID.fullmatch(cleaned_id) is None or _SECRET.fullmatch(cleaned_secret) is None:
        raise AppError(
            422,
            "invalid_fyers_config",
            "Enter the Fyers app id and app secret from the Fyers API dashboard.",
        )
    if _PIN.fullmatch(cleaned_pin) is None:
        raise AppError(422, "invalid_fyers_config", "Enter the 4-digit Fyers PIN.")
    if not _redirect_ok(cleaned_redirect):
        raise AppError(
            422,
            "invalid_fyers_config",
            "Use the Admin callback URL shown on this screen.",
        )
    cleaned_client, cleaned_totp = _totp_pair(path, client_id, totp_key)
    updates: dict[str, str | None] = {
        "FYERS_APP_ID": cleaned_id,
        "FYERS_APP_SECRET": cleaned_secret,
        "FYERS_PIN": cleaned_pin,
        "FYERS_REDIRECT_URI": cleaned_redirect,
    }
    if cleaned_client:
        updates["FYERS_CLIENT_ID"] = cleaned_client
    if cleaned_totp:
        updates["FYERS_TOTP_SECRET"] = cleaned_totp
    previous_id = _stored(path, "FYERS_APP_ID")
    previous_secret = _stored(path, "FYERS_APP_SECRET")
    if previous_id not in (None, cleaned_id) or previous_secret not in (None, cleaned_secret):
        updates["FYERS_ACCESS_TOKEN"] = None
        updates["FYERS_REFRESH_TOKEN"] = None
        updates["FYERS_ACCESS_UNTIL"] = None
        updates["FYERS_REFRESH_UNTIL"] = None
    _commit(path, updates, apply=apply)


def save_fyers_session(
    access_token: str,
    refresh_token: str,
    access_until: str,
    refresh_until: str,
    *,
    env_file: Path | None = None,
    apply: bool = True,
) -> None:
    cleaned_access = access_token.strip()
    cleaned_refresh = refresh_token.strip()
    if _TOKEN.fullmatch(cleaned_access) is None or _TOKEN.fullmatch(cleaned_refresh) is None:
        raise AppError(
            502,
            "fyers_sign_in_failed",
            "Fyers did not return a usable sign-in. Sign in again.",
        )
    path = ENV_PATH if env_file is None else env_file
    _commit(
        path,
        {
            "FYERS_ACCESS_TOKEN": cleaned_access,
            "FYERS_REFRESH_TOKEN": cleaned_refresh,
            "FYERS_ACCESS_UNTIL": access_until.strip(),
            "FYERS_REFRESH_UNTIL": refresh_until.strip(),
        },
        apply=apply,
    )


def save_fyers_access(
    access_token: str,
    access_until: str,
    *,
    env_file: Path | None = None,
    apply: bool = True,
) -> None:
    cleaned = access_token.strip()
    if _TOKEN.fullmatch(cleaned) is None:
        raise AppError(
            502,
            "fyers_refresh_failed",
            "Fyers did not refresh the connection. Sign in again if this continues.",
        )
    path = ENV_PATH if env_file is None else env_file
    _commit(
        path,
        {"FYERS_ACCESS_TOKEN": cleaned, "FYERS_ACCESS_UNTIL": access_until.strip()},
        apply=apply,
    )


def clear_fyers_access(*, env_file: Path | None = None, apply: bool = True) -> None:
    path = ENV_PATH if env_file is None else env_file
    _commit(
        path,
        {"FYERS_ACCESS_TOKEN": None, "FYERS_ACCESS_UNTIL": None},
        apply=apply,
    )


def clear_fyers_credentials(*, env_file: Path | None = None, apply: bool = True) -> None:
    path = ENV_PATH if env_file is None else env_file
    _commit(path, {key: None for key in _KEYS}, apply=apply)


def _commit(path: Path, updates: dict[str, str | None], *, apply: bool) -> None:
    with _LOCK:
        _write(path, updates)
        if apply:
            _apply(updates)


def _apply(values: dict[str, str | None]) -> None:
    for key, value in values.items():
        if value:
            os.environ[key] = value
        else:
            os.environ[key] = ""
    get_settings.cache_clear()
    clear_quote_cache()
    clear_history_cache()


def _totp_pair(path: Path, client_id: str, totp_key: str) -> tuple[str, str]:
    cleaned_client = client_id.strip().upper()
    cleaned_totp = "".join(totp_key.split()).upper()
    if cleaned_client and _CLIENT.fullmatch(cleaned_client) is None:
        raise AppError(
            422,
            "invalid_fyers_config",
            "Enter the Fyers client id used on the Fyers login page.",
        )
    if cleaned_totp and _TOTP.fullmatch(cleaned_totp) is None:
        raise AppError(
            422,
            "invalid_fyers_config",
            "Enter the Fyers external TOTP key. A 6-digit code is not the key.",
        )
    stored_client = _stored(path, "FYERS_CLIENT_ID") or ""
    stored_totp = _stored(path, "FYERS_TOTP_SECRET") or ""
    chosen_client = cleaned_client or stored_client
    chosen_totp = cleaned_totp or stored_totp
    if bool(chosen_client) != bool(chosen_totp):
        raise AppError(
            422,
            "invalid_fyers_config",
            "Enter both the Fyers client id and the TOTP key.",
        )
    return cleaned_client, cleaned_totp


def _redirect_ok(value: str) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.query or parsed.fragment:
        return False
    return parsed.path.rstrip("/") == _CALLBACK_PATH


def _write(path: Path, updates: dict[str, str | None]) -> None:
    original = path.read_text(encoding="utf-8") if path.is_file() else ""
    newline = "\r\n" if "\r\n" in original else "\n"
    seen: set[str] = set()
    rewritten: list[str] = []
    for line in original.splitlines():
        key = _fyers_key(line)
        if key is None or key not in updates:
            rewritten.append(line)
            continue
        if key in seen:
            continue
        seen.add(key)
        rewritten.append(_line(key, updates[key]))
    for key, value in updates.items():
        if key not in seen:
            rewritten.append(_line(key, value))
    body = newline.join(rewritten)
    if body and not body.endswith(newline):
        body += newline
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(body, encoding="utf-8")
    os.replace(temporary, path)


def _line(key: str, value: str | None) -> str:
    if value is None:
        return f"# {key}="
    return f"{key}={value}"


def _stored(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("#") or _fyers_key(line) != key or "=" not in line:
            continue
        value = line.split("=", 1)[1].strip()
        return value or None
    return None


def _fyers_key(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("#"):
        stripped = stripped[1:].strip()
    if "=" not in stripped:
        return None
    key = stripped.split("=", 1)[0].strip()
    if key in _KEYS:
        return key
    return None
