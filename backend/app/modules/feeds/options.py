"""Validate feed options. Each kind has its own fields. Secret values are rejected."""

import re
from urllib.parse import parse_qsl, urlparse

from app.core.errors import AppError

_FORBIDDEN_KEY = (
    "password",
    "secret",
    "token",
    "otp",
    "authorization",
    "credential",
    "api_hash",
    "api_id",
    "session",
)
_QUERY_FORBIDDEN = ("key", "token", "secret", "password", "otp", "code")
_AUTH_ENV = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_CHANNEL_ID = re.compile(r"^-?\d{5,20}$")


def _reject_keys(options: dict) -> None:
    for key in options:
        lowered = str(key).lower()
        if any(fragment in lowered for fragment in _FORBIDDEN_KEY):
            raise AppError(
                422,
                "feed_secret_rejected",
                "Feed settings cannot hold a password, token, session, or API secret. "
                "Name an environment variable instead.",
            )


def _require_mapping(options: object) -> dict:
    if not isinstance(options, dict):
        raise AppError(422, "invalid_feed_options", "Feed options must be an object.")
    return options


def validate_feed_options(kind: str, options: object, *, segment: str) -> dict:
    raw = _require_mapping(options)
    _reject_keys(raw)
    if kind == "none":
        if raw:
            raise AppError(422, "invalid_feed_options", "A sample feed has no options.")
        return {}
    if kind == "telegram":
        return _telegram(raw, segment=segment)
    if kind == "http_api":
        return _http_api(raw)
    raise AppError(422, "invalid_feed_kind", "Choose none, telegram, or http_api.")


def _telegram(options: dict, *, segment: str) -> dict:
    allowed = {"channel_id", "parser", "poll_limit"}
    unknown = sorted(set(options) - allowed)
    if unknown:
        raise AppError(
            422,
            "unknown_feed_option",
            f"Telegram settings do not include {unknown[0]}.",
        )
    parser = options.get("parser")
    if parser != "equity_calls":
        raise AppError(
            422,
            "invalid_feed_options",
            "The only Telegram parser available now is equity_calls.",
        )
    if segment != "equity":
        raise AppError(
            422,
            "segment_parser_mismatch",
            "equity_calls reads the Equity channel. This channel is a different segment.",
        )
    channel_id = str(options.get("channel_id", "")).strip()
    if not _CHANNEL_ID.fullmatch(channel_id):
        raise AppError(422, "invalid_feed_options", "Enter the Telegram channel id.")
    poll_limit = options.get("poll_limit", 40)
    if isinstance(poll_limit, bool) or not isinstance(poll_limit, int):
        raise AppError(422, "invalid_feed_options", "poll_limit must be from 1 to 100.")
    if not 1 <= poll_limit <= 100:
        raise AppError(422, "invalid_feed_options", "poll_limit must be from 1 to 100.")
    return {"channel_id": channel_id, "parser": "equity_calls", "poll_limit": poll_limit}


def _http_api(options: dict) -> dict:
    allowed = {"url", "method", "poll_seconds", "auth_env"}
    unknown = sorted(set(options) - allowed)
    if unknown:
        raise AppError(422, "unknown_feed_option", f"HTTP settings do not include {unknown[0]}.")
    url = str(options.get("url", "")).strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise AppError(422, "invalid_feed_options", "Enter an HTTP or HTTPS URL.")
    if parsed.username or parsed.password:
        raise AppError(
            422,
            "feed_secret_rejected",
            "The URL cannot carry a username or password. Name an environment variable instead.",
        )
    for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
        if any(fragment in key.lower() for fragment in _QUERY_FORBIDDEN):
            raise AppError(
                422,
                "feed_secret_rejected",
                "The URL query cannot carry a key or token. Name an environment variable instead.",
            )
    method = options.get("method", "GET")
    if method != "GET":
        raise AppError(422, "invalid_feed_options", "The HTTP reader will accept GET only.")
    poll_seconds = options.get("poll_seconds", 60)
    if isinstance(poll_seconds, bool) or not isinstance(poll_seconds, int):
        raise AppError(422, "invalid_feed_options", "poll_seconds must be from 30 to 3600.")
    if not 30 <= poll_seconds <= 3600:
        raise AppError(422, "invalid_feed_options", "poll_seconds must be from 30 to 3600.")
    cleaned = {"url": url, "method": "GET", "poll_seconds": poll_seconds}
    if "auth_env" in options and options["auth_env"] not in (None, ""):
        auth_env = str(options["auth_env"]).strip()
        if not _AUTH_ENV.fullmatch(auth_env):
            raise AppError(
                422,
                "invalid_feed_options",
                "auth_env must be the name of an environment variable, such as MARKET_FEED_KEY.",
            )
        cleaned["auth_env"] = auth_env
    return cleaned
