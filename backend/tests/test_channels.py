from app.grant_admin import grant_admin_role
from app.modules.orders.models import OrderIntent
from app.modules.signals.models import Signal
from sqlalchemy import func, select
from tests.helpers import bearer, sign_in


def test_a_new_channel_stays_closed_and_the_existing_channel_stays_open(client, db):
    session = sign_in(client, "9988776677")
    headers = bearer(session["access_token"])
    catalogue = client.get("/api/v1/scanners", headers=headers)
    assert catalogue.status_code == 200, catalogue.text
    scanner_id = catalogue.json()[0]["id"]
    activated = client.post(f"/api/v1/scanners/{scanner_id}/activate", headers=headers)
    assert activated.status_code == 200, activated.text
    synced = client.post("/api/v1/dev/mock-feed/sync", headers=headers)
    assert synced.status_code == 200, synced.text

    before = client.get("/api/v1/signals?view=all", headers=headers)
    assert before.status_code == 200, before.text
    assert "RELIANCE" in {item["symbol"] for item in before.json()["signals"]}
    assert before.json()["omitted_channels"] == []

    denied = client.post(
        "/api/v1/admin/source-channels",
        headers=headers,
        json={"name": "F&O", "segment": "fno"},
    )
    assert denied.status_code == 403

    grant_admin_role(db, "9988776677")
    db.commit()
    created = client.post(
        "/api/v1/admin/source-channels",
        headers=headers,
        json={"name": "F&O", "segment": "fno"},
    )
    assert created.status_code == 200, created.text
    created_body = created.json()
    assert created_body["channel_name"] == "F&O"
    assert created_body["segment"] == "fno"
    assert created_body["kind"] == "none"
    channel_id = created_body["channel_id"]

    renamed = client.put(
        f"/api/v1/admin/source-channels/{channel_id}",
        headers=headers,
        json={"name": "F&O Premium"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["channel_name"] == "F&O Premium"

    listed = client.get("/api/v1/source-channels", headers=headers)
    assert listed.status_code == 200, listed.text
    by_name = {item["name"]: item for item in listed.json()}
    assert by_name["Equity"]["registered"] is True
    assert by_name["F&O Premium"]["registered"] is False

    home = client.get("/api/v1/signals?view=all", headers=headers)
    assert "RELIANCE" in {item["symbol"] for item in home.json()["signals"]}
    assert home.json()["omitted_channels"] == ["F&O Premium"]

    closed = client.get(f"/api/v1/signals?view=all&channel_id={channel_id}", headers=headers)
    assert closed.status_code == 200, closed.text
    assert closed.json()["registration_required"] is True
    assert closed.json()["signals"] == []
    assert closed.json()["selected_channel_name"] == "F&O Premium"

    opened = client.put(
        f"/api/v1/source-channels/{channel_id}/registration",
        headers=headers,
        json={"active": True},
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["registered"] is True
    after = client.get(f"/api/v1/signals?view=all&channel_id={channel_id}", headers=headers)
    assert after.json()["registration_required"] is False
    assert after.json()["signals"] == []
    assert client.get("/api/v1/signals?view=all", headers=headers).json()["omitted_channels"] == []


def test_a_scanner_keeps_its_own_channels(client, db):
    session = sign_in(client, "9988776699")
    headers = bearer(session["access_token"])
    catalogue = client.get("/api/v1/scanners", headers=headers)
    assert catalogue.status_code == 200, catalogue.text
    mani_id = catalogue.json()[0]["id"]
    denied = client.post(
        "/api/v1/admin/scanners",
        headers=headers,
        json={"provider_name": "Harbour", "name": "Harbour Calls"},
    )
    assert denied.status_code == 403

    grant_admin_role(db, "9988776699")
    db.commit()
    created = client.post(
        "/api/v1/admin/scanners",
        headers=headers,
        json={"provider_name": "Harbour", "name": "Harbour Calls"},
    )
    assert created.status_code == 200, created.text
    scanner_id = created.json()["id"]
    assert created.json()["provider_name"] == "Harbour"
    second = client.post(
        "/api/v1/admin/scanners",
        headers=headers,
        json={"provider_name": "Harbour", "name": "Harbour Swing"},
    )
    assert second.status_code == 200, second.text
    listed = client.get("/api/v1/scanners", headers=headers).json()
    harbour = [item for item in listed if item["provider_name"] == "Harbour"]
    assert [item["name"] for item in harbour] == ["Harbour Calls", "Harbour Swing"]
    assert harbour[0]["price_inr"] is None
    assert harbour[0]["verified_rating"] is None

    ambiguous = client.post(
        "/api/v1/admin/source-channels",
        headers=headers,
        json={"name": "Equity Desk", "segment": "equity"},
    )
    assert ambiguous.status_code == 422

    channel = client.post(
        "/api/v1/admin/source-channels",
        headers=headers,
        json={"name": "Equity Desk", "segment": "equity", "scanner_id": scanner_id},
    )
    assert channel.status_code == 200, channel.text
    assert channel.json()["scanner_id"] == scanner_id
    assert channel.json()["channel_name"] == "Equity Desk"

    client.post(f"/api/v1/scanners/{mani_id}/activate", headers=headers)
    client.post(f"/api/v1/scanners/{scanner_id}/activate", headers=headers)
    own = client.get(f"/api/v1/source-channels?scanner_id={scanner_id}", headers=headers)
    assert own.status_code == 200, own.text
    assert [item["name"] for item in own.json()] == ["Equity Desk"]
    mani = client.get(f"/api/v1/source-channels?scanner_id={mani_id}", headers=headers)
    assert "Equity Desk" not in {item["name"] for item in mani.json()}


def test_delete_removes_an_empty_channel_and_refuses_one_with_an_order(client, db):
    session = sign_in(client, "9988776688")
    headers = bearer(session["access_token"])
    catalogue = client.get("/api/v1/scanners", headers=headers).json()
    scanner_id = catalogue[0]["id"]
    client.post(f"/api/v1/scanners/{scanner_id}/activate", headers=headers)
    missing = "00000000-0000-0000-0000-000000000000"
    denied = client.delete(f"/api/v1/admin/source-channels/{missing}", headers=headers)
    assert denied.status_code == 403

    grant_admin_role(db, "9988776688")
    db.commit()
    created = client.post(
        "/api/v1/admin/source-channels",
        headers=headers,
        json={"name": "Commodity", "segment": "commodity"},
    )
    assert created.status_code == 200, created.text
    channel_id = created.json()["channel_id"]
    assert created.json()["stored_calls"] == 0

    removed = client.delete(f"/api/v1/admin/source-channels/{channel_id}", headers=headers)
    assert removed.status_code == 204, removed.text
    listed = client.get("/api/v1/admin/source-channels", headers=headers).json()
    names = {item["channel_name"] for item in listed}
    assert "Commodity" not in names

    client.post("/api/v1/dev/mock-feed/sync", headers=headers)
    equity = next(
        item
        for item in client.get("/api/v1/admin/source-channels", headers=headers).json()
        if item["channel_code"] == "equity"
    )
    assert equity["stored_calls"] > 0
    signal_id = db.scalar(select(Signal.id).limit(1))
    me = client.get("/api/v1/me", headers=headers).json()
    db.add(
        OrderIntent(
            user_id=me["id"],
            signal_id=signal_id,
            idempotency_key="channel-delete-blocked",
            status="proposed",
            product="MIS",
            requested_quantity=1,
        )
    )
    db.commit()
    blocked = client.delete(
        f"/api/v1/admin/source-channels/{equity['channel_id']}",
        headers=headers,
    )
    assert blocked.status_code == 409, blocked.text
    assert "order record" in blocked.json()["error"]["message"]
    still = db.scalar(select(func.count()).select_from(Signal))
    assert still == equity["stored_calls"]
