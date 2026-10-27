import os
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from app.core.config import get_settings
from app.grant_admin import grant_admin_role
from app.modules.audit.models import AuditEvent
from app.modules.brokers.kite import OrderMargin, session_end
from app.modules.brokers.kite_store import save_access_token
from app.modules.brokers.service import record_zerodha
from app.modules.identity.models import User
from app.modules.orders.models import BrokerOrder, OrderIntent
from app.modules.quotes.fyers import QuoteBatch
from app.modules.scanners.mock_mani import SCANNER_CODE
from app.modules.scanners.models import Scanner
from app.modules.subscriptions.models import PaymentTransaction, ScannerSubscription
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from tests.helpers import bearer, sign_in


def _prepare(client, phone="9876543210"):
    tokens = sign_in(client, phone)
    headers = bearer(tokens["access_token"])
    catalogue = client.get("/api/v1/scanners", headers=headers)
    assert catalogue.status_code == 200, catalogue.text
    scanner = catalogue.json()[0]
    assert scanner["provider_name"] == "Mani's"
    assert scanner["verified_rating"] is None
    assert scanner["active_subscriber_count"] is None
    assert scanner["payment_status"] is None
    activated = client.post(f"/api/v1/scanners/{scanner['id']}/activate", headers=headers)
    assert activated.status_code == 200, activated.text
    assert activated.json()["payment_status"] is None
    assert activated.json()["activation_method"] == "admin_assisted"
    synced = client.post("/api/v1/dev/mock-feed/sync", headers=headers)
    assert synced.status_code == 200, synced.text
    return headers, scanner, activated.json(), synced.json()


def test_vertical_slice_shows_quantities_and_refuses_orders(client, db, tmp_path, monkeypatch):
    def quiet(*_args, **_kwargs):
        return QuoteBatch("unavailable", {})

    monkeypatch.setattr("app.modules.quotes.fyers.read_last_prices", quiet)
    monkeypatch.setattr("app.modules.signals.views.read_last_prices", quiet)
    headers, _scanner, _activation, synced = _prepare(client)
    assert synced["created"] == 5

    before = client.get("/api/v1/signals")
    assert before.status_code == 401

    actionable = client.get("/api/v1/signals?view=actionable", headers=headers)
    assert actionable.status_code == 200, actionable.text
    body = actionable.json()
    assert body["feed_mode"] == "mock"
    assert body["feed_connection"] == "mock_seed"
    assert body["entitled"] is True
    assert body["hidden_non_actionable"] == 1
    by_symbol = {item["symbol"]: item for item in body["signals"]}
    assert set(by_symbol) == {"RELIANCE", "TCS", "HDFCBANK", "SBIN"}
    assert by_symbol["RELIANCE"]["provider_values"]["source"] == "provider"
    assert by_symbol["RELIANCE"]["quantivo_values"]["source"] == "quantivo"
    assert by_symbol["RELIANCE"]["suggested_quantity"] == 27
    assert by_symbol["RELIANCE"]["segment"] == "equity"
    assert by_symbol["RELIANCE"]["channel_code"] == "equity"
    assert by_symbol["RELIANCE"]["horizon_raw"] == "Short term"
    assert by_symbol["TCS"]["horizon_raw"] == "Intraday to 7 days"
    assert by_symbol["TCS"]["suggested_quantity"] == 11
    assert "not the amount at risk" in by_symbol["RELIANCE"]["quantivo_values"]["formula"]

    detail = client.get(f"/api/v1/signals/{by_symbol['RELIANCE']['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["executable"] is True
    assert detail.json()["provider_values"]["targets"][0]["risk_reward"] == "1.33"
    assert detail.json()["broker"]["order_placement"] == "disabled"
    assert detail.json()["broker"]["status"] == "disconnected"

    wrong_quantity = client.post(
        "/api/v1/orders",
        headers=headers,
        json={
            "signal_id": by_symbol["RELIANCE"]["id"],
            "idempotency_key": "reliance-wrong-qty",
            "product": "MIS",
            "quantity": 28,
        },
    )
    assert wrong_quantity.status_code == 409
    assert wrong_quantity.json()["error"]["code"] == "broker_not_connected"

    not_connected = client.post(
        "/api/v1/orders",
        headers=headers,
        json={
            "signal_id": by_symbol["RELIANCE"]["id"],
            "idempotency_key": "reliance-no-broker",
            "product": "MIS",
            "quantity": 27,
        },
    )
    assert not_connected.status_code == 409
    assert not_connected.json()["error"]["code"] == "broker_not_connected"

    monkeypatch.setattr("app.modules.brokers.kite_store.SECRET_ROOT", tmp_path)
    os.environ["KITE_API_KEY"] = "kiteapi01"
    os.environ["KITE_API_SECRET"] = "kitesecret01"
    get_settings.cache_clear()
    try:
        user = db.scalar(select(User).where(User.phone_e164 == "+919876543210"))
        assert user is not None
        monkeypatch.setattr(
            "app.modules.orders.service.equity_order_margin",
            lambda *_args, **_kwargs: OrderMargin(Decimal("10.00"), Decimal("1000000.00")),
        )
        save_access_token(str(user.id), "kiteAccessTokenValue123", secret_root=tmp_path)
        record_zerodha(
            db,
            user.id,
            client_id="NXJ652",
            exchanges=["NSE"],
            session_end=session_end(datetime.now(ZoneInfo("Asia/Kolkata"))),
            correlation_id=None,
        )
        connected = client.get(f"/api/v1/signals/{by_symbol['RELIANCE']['id']}", headers=headers)
        assert connected.json()["broker"]["code"] == "zerodha"
        assert connected.json()["broker"]["status"] == "connected"
        assert "does not send an order" in connected.json()["broker"]["message"]

        saved = client.post(
            "/api/v1/orders",
            headers=headers,
            json={
                "signal_id": by_symbol["RELIANCE"]["id"],
                "idempotency_key": "reliance-confirm",
                "product": "MIS",
                "quantity": 27,
            },
        )
        assert saved.status_code == 200
        assert saved.json()["status"] == "proposed"
        assert saved.json()["quantity"] == 27
        assert saved.json()["sent_to_broker"] is False
        assert saved.json()["protection"] == "not_active"
        assert "not sent" in saved.json()["message"]
        book = client.get("/api/v1/orders", headers=headers)
        assert book.status_code == 200
        assert len(book.json()) == 1
        assert book.json()[0]["symbol"] == "RELIANCE"
        assert book.json()[0]["status"] == "proposed"
        assert book.json()[0]["side"] == "BUY"
        assert book.json()[0]["sent_to_broker"] is False
        again = client.post(
            "/api/v1/orders",
            headers=headers,
            json={
                "signal_id": by_symbol["RELIANCE"]["id"],
                "idempotency_key": "reliance-confirm",
                "product": "MIS",
                "quantity": 27,
            },
        )
        assert again.status_code == 200
        assert again.json()["id"] == saved.json()["id"]
        changed = client.post(
            "/api/v1/orders",
            headers=headers,
            json={
                "signal_id": by_symbol["RELIANCE"]["id"],
                "idempotency_key": "reliance-confirm",
                "product": "CNC",
                "quantity": 27,
            },
        )
        assert changed.status_code == 409
        assert changed.json()["error"]["code"] == "idempotency_conflict"
        smaller = client.post(
            "/api/v1/orders",
            headers=headers,
            json={
                "signal_id": by_symbol["RELIANCE"]["id"],
                "idempotency_key": "reliance-smaller",
                "product": "MIS",
                "quantity": 10,
            },
        )
        assert smaller.status_code == 200
        assert smaller.json()["id"] == saved.json()["id"]
        assert smaller.json()["quantity"] == 10
        preview = client.post(
            "/api/v1/orders/preview",
            headers=headers,
            json={
                "signal_id": by_symbol["RELIANCE"]["id"],
                "side": "BUY",
                "product": "MIS",
                "trigger_price": "2450.00",
                "stop_loss": "2400.00",
                "targets": [
                    {"label": "T1", "price": "2474.00"},
                    {"label": "T2", "price": "2490.00"},
                ],
            },
        )
        assert preview.status_code == 200
        assert preview.json()["ok"] is True
        assert preview.json()["quantity"] != 27
        edited = client.post(
            "/api/v1/orders",
            headers=headers,
            json={
                "signal_id": by_symbol["RELIANCE"]["id"],
                "idempotency_key": "reliance-edited",
                "product": "MIS",
                "quantity": preview.json()["quantity"],
                "side": "BUY",
                "trigger_price": "2450.00",
                "stop_loss": "2400.00",
                "targets": [
                    {"label": "T1", "price": "2474.00"},
                    {"label": "T2", "price": "2490.00"},
                ],
            },
        )
        assert edited.status_code == 200
        assert edited.json()["id"] == saved.json()["id"]
        assert edited.json()["stop_loss"] == "2400.00"
        assert edited.json()["quantity"] == preview.json()["quantity"]
        larger = client.post(
            "/api/v1/orders",
            headers=headers,
            json={
                "signal_id": by_symbol["RELIANCE"]["id"],
                "idempotency_key": "reliance-larger",
                "product": "MIS",
                "quantity": 100,
            },
        )
        assert larger.status_code == 200
        assert larger.json()["id"] == saved.json()["id"]
        assert larger.json()["quantity"] == 100
        monkeypatch.setattr(
            "app.modules.orders.service.equity_order_margin",
            lambda *_args, **_kwargs: OrderMargin(Decimal("900000.00"), Decimal("1000.00")),
        )
        short = client.post(
            "/api/v1/orders",
            headers=headers,
            json={
                "signal_id": by_symbol["RELIANCE"]["id"],
                "idempotency_key": "reliance-short",
                "product": "MIS",
                "quantity": 500,
            },
        )
        assert short.status_code == 409
        assert short.json()["error"]["code"] == "insufficient_margin"
        listed = client.get("/api/v1/orders", headers=headers)
        assert len(listed.json()) == 1
        assert listed.json()[0]["id"] == saved.json()["id"]
        assert listed.json()[0]["quantity"] == 100
        assert listed.json()[0]["stop_loss"] == "2432.00"
        order_id = saved.json()["id"]
        blocked_delete = client.delete(f"/api/v1/admin/orders/{order_id}", headers=headers)
        assert blocked_delete.status_code == 403
        intent = db.get(OrderIntent, UUID(order_id))
        assert intent is not None
        intent.status = "cancelled"
        db.commit()
        grant_admin_role(db, "9876543210")
        db.commit()
        kept = client.delete(f"/api/v1/admin/orders/{order_id}", headers=headers)
        assert kept.status_code == 409
        assert kept.json()["error"]["code"] == "order_already_sent"
        intent.status = "proposed"
        db.commit()
        removed = client.delete(f"/api/v1/admin/orders/{order_id}", headers=headers)
        assert removed.status_code == 204
        assert client.get("/api/v1/admin/orders", headers=headers).json() == []
        assert client.get("/api/v1/orders", headers=headers).json() == []
        missing = client.delete(f"/api/v1/admin/orders/{order_id}", headers=headers)
        assert missing.status_code == 404
        db.expire_all()
        deleted = db.scalar(select(AuditEvent).where(AuditEvent.action == "order.deleted"))
        assert deleted is not None
        assert deleted.payload["symbol"] == "RELIANCE"
        assert deleted.payload["status"] == "proposed"
    finally:
        for key in ("KITE_API_KEY", "KITE_API_SECRET"):
            os.environ.pop(key, None)
        get_settings.cache_clear()

    everything = client.get("/api/v1/signals?view=all", headers=headers).json()
    assert everything["hidden_non_actionable"] == 1
    statuses = {item["symbol"]: item["status"] for item in everything["signals"]}
    assert statuses["HDFCBANK"] == "active"
    assert statuses["INFY"] == "expired"
    assert statuses["SBIN"] == "active"
    closed = next(item for item in everything["signals"] if item["symbol"] == "INFY")
    blocked = client.post(
        "/api/v1/orders",
        headers=headers,
        json={
            "signal_id": closed["id"],
            "idempotency_key": "infy-expired",
            "product": "MIS",
            "quantity": closed["suggested_quantity"],
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "signal_not_actionable"

    db.rollback()
    assert db.scalar(select(func.count()).select_from(OrderIntent)) == 0
    assert db.scalar(select(func.count()).select_from(BrokerOrder)) == 0
    assert db.scalar(select(func.count()).select_from(PaymentTransaction)) == 0


def test_activation_is_idempotent_and_signals_are_not_shared(client):
    headers, scanner, activation, _synced = _prepare(client, "9876543211")
    again = client.post(f"/api/v1/scanners/{scanner['id']}/activate", headers=headers)
    assert again.json()["subscription_id"] == activation["subscription_id"]

    outsider = bearer(sign_in(client, "9876543212")["access_token"])
    hidden = client.get("/api/v1/signals", headers=outsider)
    assert hidden.status_code == 200
    assert hidden.json()["entitled"] is False
    assert hidden.json()["signals"] == []
    sample = client.get("/api/v1/signals?view=all", headers=headers).json()["signals"][0]
    missing = client.get(f"/api/v1/signals/{sample['id']}", headers=outsider)
    assert missing.status_code == 404


def test_second_active_subscription_is_rejected_by_the_database(client, db):
    headers, scanner, _activation, _synced = _prepare(client, "9876543213")
    me = client.get("/api/v1/me", headers=headers).json()
    db.add(
        ScannerSubscription(
            user_id=UUID(me["id"]),
            scanner_id=UUID(scanner["id"]),
            status="active",
            activation_method="admin_assisted",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_repeat_feed_sync_does_not_duplicate_signals(client, db):
    headers, _scanner, _activation, first = _prepare(client, "9876543214")
    assert first["created"] == 5
    second = client.post("/api/v1/dev/mock-feed/sync", headers=headers)
    assert second.json() == {"created": 0, "unchanged": 5, "revised": 0}
    db.rollback()
    scanner = db.scalar(select(Scanner).where(Scanner.code == SCANNER_CODE))
    assert scanner is not None
