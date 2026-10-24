from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.modules.orders.models import BrokerOrder, OrderIntent
from app.modules.scanners.mock_mani import SCANNER_CODE
from app.modules.scanners.models import Scanner
from app.modules.subscriptions.models import PaymentTransaction, ScannerSubscription
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


def test_vertical_slice_shows_quantities_and_refuses_orders(client, db):
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
            "quantity": 1,
        },
    )
    assert wrong_quantity.status_code == 409
    assert wrong_quantity.json()["error"]["code"] == "quantity_mismatch"

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

    connected = client.post("/api/v1/broker/connections/simulated", headers=headers)
    assert connected.status_code == 200, connected.text
    assert connected.json()["stores_credentials"] is False
    assert connected.json()["status"] == "connected"

    refused = client.post(
        "/api/v1/orders",
        headers=headers,
        json={
            "signal_id": by_symbol["RELIANCE"]["id"],
            "idempotency_key": "reliance-disabled",
            "product": "MIS",
            "quantity": 27,
        },
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "trading_disabled"

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
