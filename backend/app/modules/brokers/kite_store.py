"""Kite app secrets stay in the server environment.

Each trader's access token stays in the secret directory.
Neither value is written to a table, a log, or an audit payload.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from app.core.config import get_settings
from app.core.errors import AppError

ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
SECRET_ROOT = Path(__file__).resolve().parents[4] / ".quantivo" / "secrets" / "zerodha"
_KEYS = ("KITE_API_KEY", "KITE_API_SECRET", "KITE_REDIRECT_URI")
_KEY = re.compile(r"^[A-Za-z0-9]{8,32}$")
_TOKEN = re.compile(r"^[A-Za-z0-9._~+/=-]{16,4096}$")
_CALLBACK_PATH = "/api/v1/broker/zerodha/callback"
_LOCK = threading.Lock()


def save_kite_app(
    api_key: str,
    api_secret: str,
    redirect_uri: str,
    *,
    env_file: Path | None = None,
    apply: bool = True,
) -> bool:
    """Save the Kite app. Returns whether the key or secret changed."""
    cleaned_key = api_key.strip()
    cleaned_secret = api_secret.strip()
    cleaned_redirect = redirect_uri.strip()
    if _KEY.fullmatch(cleaned_key) is None or _KEY.fullmatch(cleaned_secret) is None:
        raise AppError(
            422,
            "invalid_kite_config",
            "Enter the Kite Connect api key and api secret from the Zerodha developer console.",
        )
    if not _redirect_ok(cleaned_redirect):
        raise AppError(
            422,
            "invalid_kite_config",
            "Use the Admin callback URL shown on this screen.",
        )
    path = ENV_PATH if env_file is None else env_file
    previous_key = _stored(path, "KITE_API_KEY")
    previous_secret = _stored(path, "KITE_API_SECRET")
    changed = previous_key not in (None, cleaned_key) or previous_secret not in (
        None,
        cleaned_secret,
    )
    _commit(
        path,
        {
            "KITE_API_KEY": cleaned_key,
            "KITE_API_SECRET": cleaned_secret,
            "KITE_REDIRECT_URI": cleaned_redirect,
        },
        apply=apply,
    )
    return changed


def clear_kite_app(*, env_file: Path | None = None, apply: bool = True) -> None:
    path = ENV_PATH if env_file is None else env_file
    _commit(path, {key: None for key in _KEYS}, apply=apply)


def save_access_token(
    user_id: str,
    access_token: str,
    *,
    secret_root: Path | None = None,
) -> None:
    cleaned = access_token.strip()
    if _TOKEN.fullmatch(cleaned) is None:
        raise AppError(
            502,
            "kite_sign_in_failed",
            "Zerodha did not return a usable sign-in. Sign in again.",
        )
    path = _token_path(user_id, secret_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"access_token": cleaned}), encoding="utf-8")
    os.replace(temporary, path)


def read_access_token(user_id: str, *, secret_root: Path | None = None) -> str | None:
    path = _token_path(user_id, secret_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or _TOKEN.fullmatch(token) is None:
        return None
    return token


def clear_access_token(user_id: str, *, secret_root: Path | None = None) -> None:
    path = _token_path(user_id, secret_root)
    if path.is_file():
        path.unlink()


def clear_access_tokens(*, secret_root: Path | None = None) -> None:
    root = SECRET_ROOT if secret_root is None else secret_root
    if not root.is_dir():
        return
    for path in root.glob("*.json"):
        path.unlink()


def _token_path(user_id: str, secret_root: Path | None) -> Path:
    root = SECRET_ROOT if secret_root is None else secret_root
    return root / f"{UUID(user_id)}.json"


def _redirect_ok(value: str) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.query or parsed.fragment:
        return False
    return parsed.path.rstrip("/") == _CALLBACK_PATH


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
            os.environ.pop(key, None)
    get_settings.cache_clear()


def _write(path: Path, updates: dict[str, str | None]) -> None:
    original = path.read_text(encoding="utf-8") if path.is_file() else ""
    newline = "\r\n" if "\r\n" in original else "\n"
    seen: set[str] = set()
    rewritten: list[str] = []
    for line in original.splitlines():
        key = _kite_key(line)
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
    path.parent.mkdir(parents=True, exist_ok=True)
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
        if line.strip().startswith("#") or _kite_key(line) != key or "=" not in line:
            continue
        value = line.split("=", 1)[1].strip()
        return value or None
    return None


def _kite_key(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("#"):
        stripped = stripped[1:].strip()
    if "=" not in stripped:
        return None
    key = stripped.split("=", 1)[0].strip()
    if key in _KEYS:
        return key
    return None
