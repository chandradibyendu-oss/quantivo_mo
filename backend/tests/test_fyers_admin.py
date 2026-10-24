import json
import os
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.grant_admin import grant_admin_role
from app.modules.audit.models import AuditEvent
from app.modules.quotes.credentials import (
    clear_fyers_credentials,
    save_fyers_app,
    save_fyers_session,
)
from app.modules.quotes.session import access_valid_until, ensure_access_token
from sqlalchemy import select
from tests.helpers import bearer, sign_in

IST = ZoneInfo("Asia/Kolkata")
_APP_ID = "TESTAPP-100"
_SECRET = "fyersSecretValue123"
_PIN = "1234"
_REDIRECT = "http://127.0.0.1:8000/api/v1/admin/fyers/callback"
_ACCESS = "fyersAccessTokenValue123456"
_REFRESH = "fyersRefreshTokenValue123456"
_ENV_KEYS = (
    "FYERS_APP_ID",
    "FYERS_APP_SECRET",
    "FYERS_PIN",
    "FYERS_ACCESS_TOKEN",
    "FYERS_REFRESH_TOKEN",
    "FYERS_ACCESS_UNTIL",
    "FYERS_REFRESH_UNTIL",
    "FYERS_REDIRECT_URI",
)


def test_the_env_file_keeps_other_lines_and_drops_a_removed_token(tmp_path):
    path = tmp_path / ".env"
    path.write_text("DATABASE_URL=postgresql+psycopg://local/quantivo\n# FYERS_APP_ID=\n")
    save_fyers_app(_APP_ID, _SECRET, _PIN, _REDIRECT, env_file=path, apply=False)
    save_fyers_session(
        _ACCESS,
        _REFRESH,
        "2026-10-25T06:30:00+05:30",
        "2026-11-08T10:00:00+05:30",
        env_file=path,
        apply=False,
    )
    text = path.read_text(encoding="utf-8")
    assert "DATABASE_URL=postgresql+psycopg://local/quantivo" in text
    assert f"FYERS_APP_ID={_APP_ID}" in text
    assert f"FYERS_ACCESS_TOKEN={_ACCESS}" in text
    assert text.count("FYERS_APP_ID=") == 1

    save_fyers_app("OTHER-100", "replacementSecret123", _PIN, _REDIRECT, env_file=path, apply=False)
    replaced = path.read_text(encoding="utf-8")
    assert "FYERS_APP_ID=OTHER-100" in replaced
    assert _ACCESS not in replaced
    assert _REFRESH not in replaced

    clear_fyers_credentials(env_file=path, apply=False)
    cleared = path.read_text(encoding="utf-8")
    assert "DATABASE_URL=postgresql+psycopg://local/quantivo" in cleared
    assert _SECRET not in cleared
    assert _PIN not in cleared
    assert "FYERS_APP_ID=" not in cleared.replace("# FYERS_APP_ID=", "")


def test_the_access_token_lasts_until_the_next_morning_and_the_sign_in_lasts_15_days():
    morning = datetime(2026, 10, 24, 6, 0, tzinfo=IST)
    at_boundary = datetime(2026, 10, 24, 6, 30, tzinfo=IST)
    afternoon = datetime(2026, 10, 24, 15, 23, tzinfo=IST)
    assert access_valid_until(morning) == datetime(2026, 10, 24, 6, 30, tzinfo=IST)
    assert access_valid_until(at_boundary) == datetime(2026, 10, 25, 6, 30, tzinfo=IST)
    assert access_valid_until(afternoon) == datetime(2026, 10, 25, 6, 30, tzinfo=IST)


def test_a_morning_token_is_minted_without_another_sign_in(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("LOG_LEVEL=INFO\n")
    monkeypatch.setattr("app.modules.quotes.credentials.ENV_PATH", env_file)
    monkeypatch.setattr("app.modules.quotes.session._failed_at", None)
    previous = {key: os.environ.get(key) for key in _ENV_KEYS}
    issued = datetime(2026, 10, 24, 10, 0, tzinfo=IST)
    for key, value in {
        "FYERS_APP_ID": _APP_ID,
        "FYERS_APP_SECRET": _SECRET,
        "FYERS_PIN": _PIN,
        "FYERS_REDIRECT_URI": _REDIRECT,
        "FYERS_ACCESS_TOKEN": "oldAccessTokenValue123456",
        "FYERS_REFRESH_TOKEN": _REFRESH,
        "FYERS_ACCESS_UNTIL": datetime(2026, 10, 24, 6, 30, tzinfo=IST).isoformat(),
        "FYERS_REFRESH_UNTIL": datetime(2026, 11, 8, 10, 0, tzinfo=IST).isoformat(),
    }.items():
        os.environ[key] = value
    get_settings.cache_clear()
    calls = {"n": 0}

    def post(url, payload):
        calls["n"] += 1
        assert url.endswith("/validate-refresh-token")
        assert payload["pin"] == _PIN
        assert payload["refresh_token"] == _REFRESH
        assert _SECRET not in json.dumps(payload)
        return json.dumps({"s": "ok", "access_token": "newAccessTokenValue123456"})

    try:
        assert ensure_access_token(post=post, now=issued) is True
        assert calls["n"] == 1
        assert get_settings().fyers_access_token == "newAccessTokenValue123456"
        stored = env_file.read_text(encoding="utf-8")
        assert "newAccessTokenValue123456" in stored
        assert "oldAccessTokenValue123456" not in stored
        later = datetime(2026, 10, 24, 11, 0, tzinfo=IST)
        assert ensure_access_token(post=post, now=later) is True
        assert calls["n"] == 1
    finally:
        _restore(previous)


def test_a_sign_in_older_than_15_days_is_not_refreshed(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("LOG_LEVEL=INFO\n")
    monkeypatch.setattr("app.modules.quotes.credentials.ENV_PATH", env_file)
    monkeypatch.setattr("app.modules.quotes.session._failed_at", None)
    previous = {key: os.environ.get(key) for key in _ENV_KEYS}
    for key, value in {
        "FYERS_APP_ID": _APP_ID,
        "FYERS_APP_SECRET": _SECRET,
        "FYERS_PIN": _PIN,
        "FYERS_REDIRECT_URI": _REDIRECT,
        "FYERS_ACCESS_TOKEN": _ACCESS,
        "FYERS_REFRESH_TOKEN": _REFRESH,
        "FYERS_ACCESS_UNTIL": datetime(2026, 10, 24, 6, 30, tzinfo=IST).isoformat(),
        "FYERS_REFRESH_UNTIL": datetime(2026, 10, 20, 10, 0, tzinfo=IST).isoformat(),
    }.items():
        os.environ[key] = value
    get_settings.cache_clear()

    def post(url, payload):
        raise AssertionError(url + json.dumps(payload))

    try:
        minted = ensure_access_token(post=post, now=datetime(2026, 10, 24, 10, 0, tzinfo=IST))
        assert minted is False
        assert get_settings().fyers_access_token == ""
        assert get_settings().fyers_refresh_token == _REFRESH
        assert _ACCESS not in env_file.read_text(encoding="utf-8")
    finally:
        _restore(previous)


def test_a_trader_cannot_read_or_save_fyers(client):
    session = sign_in(client, "9988776655")
    headers = bearer(session["access_token"])
    seen = client.get("/api/v1/admin/fyers", headers=headers)
    assert seen.status_code == 403
    saved = client.put(
        "/api/v1/admin/fyers",
        headers=headers,
        json={"app_id": _APP_ID, "app_secret": _SECRET, "pin": _PIN, "redirect_uri": _REDIRECT},
    )
    assert saved.status_code == 403
    assert _SECRET not in saved.text
    started = client.post("/api/v1/admin/fyers/connect", headers=headers)
    assert started.status_code == 403


def test_an_admin_signs_in_once_and_the_secrets_stay_on_the_server(
    client, db, tmp_path, monkeypatch
):
    env_file = tmp_path / ".env"
    env_file.write_text("LOG_LEVEL=INFO\n")
    monkeypatch.setattr("app.modules.quotes.credentials.ENV_PATH", env_file)
    monkeypatch.setattr("app.modules.quotes.session._failed_at", None)
    monkeypatch.setattr(
        "app.modules.quotes.session._now",
        lambda: datetime(2026, 10, 24, 10, 0, tzinfo=IST),
    )
    previous = {key: os.environ.get(key) for key in _ENV_KEYS}
    session = sign_in(client, "9988776644")
    grant_admin_role(db, "9988776644")
    db.commit()
    headers = bearer(session["access_token"])

    def post(url, payload):
        assert url.endswith("/validate-authcode")
        raw = json.dumps(payload)
        assert _SECRET not in raw
        assert _PIN not in raw
        assert payload["code"] == "auth-code-from-fyers"
        return json.dumps({"s": "ok", "access_token": _ACCESS, "refresh_token": _REFRESH})

    monkeypatch.setattr("app.modules.quotes.session._post", post)
    try:
        saved = client.put(
            "/api/v1/admin/fyers",
            headers=headers,
            json={"app_id": _APP_ID, "app_secret": _SECRET, "pin": _PIN, "redirect_uri": _REDIRECT},
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["app_saved"] is True
        assert body["connected"] is False
        assert body["configured"] is False
        assert _SECRET not in saved.text
        assert _PIN not in saved.text
        assert _APP_ID not in saved.text

        rejected = client.put(
            "/api/v1/admin/fyers",
            headers=headers,
            json={
                "app_id": _APP_ID,
                "app_secret": "bad secret",
                "pin": "12",
                "redirect_uri": _REDIRECT,
            },
        )
        assert rejected.status_code == 422
        assert "bad secret" not in rejected.text
        assert "bad secret" not in env_file.read_text(encoding="utf-8")

        started = client.post("/api/v1/admin/fyers/connect", headers=headers)
        assert started.status_code == 200, started.text
        login_url = started.json()["url"]
        assert _SECRET not in login_url
        assert _PIN not in login_url
        state = parse_qs(urlparse(login_url).query)["state"][0]

        callback = client.get(
            "/api/v1/admin/fyers/callback",
            params={"state": state, "auth_code": "auth-code-from-fyers"},
        )
        assert callback.status_code == 200, callback.text
        assert "Fyers is connected" in callback.text
        assert _ACCESS not in callback.text
        assert _REFRESH not in callback.text
        stored = env_file.read_text(encoding="utf-8")
        assert f"FYERS_ACCESS_TOKEN={_ACCESS}" in stored
        assert f"FYERS_REFRESH_TOKEN={_REFRESH}" in stored
        assert "FYERS_REFRESH_UNTIL=2026-11-08T10:00:00+05:30" in stored

        seen = client.get("/api/v1/admin/fyers", headers=headers)
        assert seen.status_code == 200
        assert seen.json()["connected"] is True
        assert seen.json()["refresh_until"] == "2026-11-08"
        assert "Connected until 8 Nov 2026" in seen.json()["detail"]
        assert _ACCESS not in seen.text
        assert _SECRET not in seen.text

        replay = client.get(
            "/api/v1/admin/fyers/callback",
            params={"state": state, "auth_code": "auth-code-from-fyers"},
        )
        assert replay.status_code == 400
        assert _ACCESS not in replay.text

        audit = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "quotes.fyers_connected")
        ).all()
        assert audit[-1].payload == {"connected": True, "refresh_until": "2026-11-08"}
        assert _ACCESS not in str(audit[-1].payload)
        assert _SECRET not in str(audit[-1].payload)

        removed = client.delete("/api/v1/admin/fyers", headers=headers)
        assert removed.status_code == 200, removed.text
        assert removed.json()["connected"] is False
        assert removed.json()["app_saved"] is False
        cleared = env_file.read_text(encoding="utf-8")
        assert _ACCESS not in cleared
        assert _REFRESH not in cleared
        assert _SECRET not in cleared
        assert _PIN not in cleared
    finally:
        _restore(previous)


def _restore(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()
