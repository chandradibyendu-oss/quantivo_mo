import io
import os
import urllib.error
from datetime import datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.errors import AppError
from app.grant_admin import grant_admin_role
from app.modules.audit.models import AuditEvent
from app.modules.brokers.kite import (
    MarginUnavailable,
    complete_login,
    equity_order_margin,
    session_end,
)
from app.modules.brokers.kite_store import read_access_token
from app.modules.brokers.models import BrokerConnection
from sqlalchemy import select
from tests.helpers import bearer, sign_in

IST = ZoneInfo("Asia/Kolkata")
_KEY = "kiteapi01"
_SECRET = "kitesecret01"
_REDIRECT = "http://127.0.0.1:8001/api/v1/broker/zerodha/callback"
_ACCESS = "kiteAccessTokenValue123"
_CLIENT = "AB1234"


def test_the_session_ends_at_the_next_six_am():
    morning = session_end(datetime(2026, 10, 25, 5, 30, tzinfo=IST))
    assert morning == datetime(2026, 10, 25, 6, 0, tzinfo=IST)
    after_open = session_end(datetime(2026, 10, 25, 9, 15, tzinfo=IST))
    assert after_open == datetime(2026, 10, 26, 6, 0, tzinfo=IST)
    at_flush = session_end(datetime(2026, 10, 25, 6, 0, tzinfo=IST))
    assert at_flush == datetime(2026, 10, 26, 6, 0, tzinfo=IST)


def test_a_trader_sign_in_stores_the_token_outside_the_table(client, db, tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DATABASE_URL=postgresql+psycopg://local/quantivo\n")
    secrets = tmp_path / "secrets"
    monkeypatch.setattr("app.modules.brokers.kite_store.ENV_PATH", env)
    monkeypatch.setattr("app.modules.brokers.kite_store.SECRET_ROOT", secrets)

    def post(_url, form):
        assert form["api_key"] == _KEY
        assert "api_secret" not in form
        return {
            "status": "success",
            "data": {
                "user_id": _CLIENT,
                "access_token": _ACCESS,
                "exchanges": ["NSE", "NFO"],
            },
        }

    monkeypatch.setattr("app.modules.brokers.kite._post", post)
    try:
        session = sign_in(client)
        grant_admin_role(db, "9876543210")
        db.commit()
        headers = bearer(session["access_token"])
        saved = client.put(
            "/api/v1/admin/zerodha",
            headers=headers,
            json={"api_key": _KEY, "api_secret": _SECRET, "redirect_uri": _REDIRECT},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["app_saved"] is True
        assert _SECRET not in saved.text

        started = client.post("/api/v1/broker/zerodha/connect", headers=headers)
        assert started.status_code == 200, started.text
        parsed = urlparse(started.json()["url"])
        query = parse_qs(parsed.query)
        assert query["api_key"] == [_KEY]
        assert _SECRET not in started.text
        state = parse_qs(query["redirect_params"][0])["state"][0]

        callback = client.get(
            "/api/v1/broker/zerodha/callback",
            params={"request_token": "requestToken123", "status": "success", "state": state},
        )
        assert callback.status_code == 200, callback.text
        assert _ACCESS not in callback.text
        assert "return to Account" in callback.text

        account = client.get("/api/v1/broker/zerodha", headers=headers)
        assert account.status_code == 200, account.text
        body = account.json()
        assert body["status"] == "connected"
        assert body["client_id"] == _CLIENT
        assert "6:00 AM IST" in body["detail"]
        assert _ACCESS not in account.text

        connection = db.scalar(
            select(BrokerConnection).where(BrokerConnection.broker_code == "zerodha")
        )
        assert connection is not None
        assert connection.external_account_ref == _CLIENT
        assert connection.status == "connected"
        stored = read_access_token(str(connection.user_id), secret_root=secrets)
        assert stored == _ACCESS
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "broker.zerodha_connected")
        ).all()
        assert events
        assert _ACCESS not in str(events[-1].payload)
    finally:
        for key in ("KITE_API_KEY", "KITE_API_SECRET", "KITE_REDIRECT_URI"):
            os.environ.pop(key, None)
        get_settings.cache_clear()


def test_a_finished_session_is_expired_and_the_token_is_removed(client, db, tmp_path, monkeypatch):
    from app.modules.brokers.kite_store import save_access_token
    from app.modules.brokers.service import record_zerodha, zerodha_account
    from app.modules.identity.models import User

    secrets = tmp_path / "secrets"
    monkeypatch.setattr("app.modules.brokers.kite_store.SECRET_ROOT", secrets)
    os.environ["KITE_API_KEY"] = _KEY
    os.environ["KITE_API_SECRET"] = _SECRET
    get_settings.cache_clear()
    try:
        sign_in(client, "9123456780")
        user = db.scalar(select(User).where(User.phone_e164 == "+919123456780"))
        assert user is not None
        signed_in = datetime(2026, 10, 25, 9, 15, tzinfo=IST)
        save_access_token(str(user.id), _ACCESS, secret_root=secrets)
        record_zerodha(
            db,
            user.id,
            client_id=_CLIENT,
            exchanges=["NSE"],
            session_end=session_end(signed_in),
            correlation_id=None,
        )
        connection = db.scalar(
            select(BrokerConnection).where(
                BrokerConnection.user_id == user.id,
                BrokerConnection.broker_code == "zerodha",
            )
        )
        connection.last_authenticated_at = signed_in
        db.commit()
        later = datetime(2026, 10, 26, 6, 0, tzinfo=IST)
        account = zerodha_account(db, user.id, later)
        assert account.status == "expired"
        assert "ended at 6:00 AM IST" in account.detail
        assert read_access_token(str(user.id), secret_root=secrets) is None
    finally:
        for key in ("KITE_API_KEY", "KITE_API_SECRET"):
            os.environ.pop(key, None)
        get_settings.cache_clear()


def test_complete_login_rejects_a_missing_state(tmp_path, monkeypatch):
    monkeypatch.setattr("app.modules.brokers.kite_store.SECRET_ROOT", tmp_path)
    try:
        complete_login("missing", "requestToken123", "success", post=lambda *_args: {})
    except AppError as caught:
        assert caught.code == "kite_sign_in_failed"
    else:
        raise AssertionError("missing state was accepted")


class _KiteBody:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False


def test_equity_margin_reads_the_order_total_and_the_available_net(monkeypatch):
    monkeypatch.setattr(
        "app.modules.brokers.kite.read_access_token",
        lambda *_args, **_kwargs: _ACCESS,
    )
    monkeypatch.setenv("KITE_API_KEY", _KEY)
    get_settings.cache_clear()

    def opener(request, timeout):
        assert timeout == 15
        assert request.get_header("Authorization") == f"token {_KEY}:{_ACCESS}"
        if request.full_url.endswith("/user/margins"):
            return _KiteBody(b'{"status":"success","data":{"equity":{"net":50000.5}}}')
        assert b'"price": 2450.0000' in request.data
        assert _ACCESS.encode() not in request.data
        return _KiteBody(b'{"status":"success","data":[{"total":1200.25}]}')

    try:
        margin = equity_order_margin(
            "user-1",
            exchange="NSE",
            tradingsymbol="RELIANCE",
            transaction_type="BUY",
            product="MIS",
            quantity=100,
            price=Decimal("2450"),
            opener=opener,
        )
    finally:
        os.environ.pop("KITE_API_KEY", None)
        get_settings.cache_clear()
    assert margin.required == Decimal("1200.25")
    assert margin.available == Decimal("50000.50")


def test_a_refused_margin_read_carries_no_token(monkeypatch):
    monkeypatch.setattr(
        "app.modules.brokers.kite.read_access_token",
        lambda *_args, **_kwargs: _ACCESS,
    )
    monkeypatch.setenv("KITE_API_KEY", _KEY)
    get_settings.cache_clear()

    def opener(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 403, "no", hdrs=None, fp=io.BytesIO(b"hidden")
        )

    try:
        equity_order_margin(
            "user-1",
            exchange="NSE",
            tradingsymbol="RELIANCE",
            transaction_type="BUY",
            product="CNC",
            quantity=1,
            price=Decimal("10"),
            opener=opener,
        )
    except MarginUnavailable as caught:
        assert _ACCESS not in str(caught)
    else:
        raise AssertionError("a refused margin read was accepted")
    finally:
        os.environ.pop("KITE_API_KEY", None)
        get_settings.cache_clear()
