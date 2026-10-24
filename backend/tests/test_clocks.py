from app.grant_admin import grant_admin_role
from app.modules.audit.models import AuditEvent
from sqlalchemy import select
from tests.helpers import bearer, sign_in


def test_a_trader_cannot_read_or_save_the_clocks(client):
    headers = bearer(sign_in(client, "9988776655")["access_token"])
    assert client.get("/api/v1/admin/call-clocks", headers=headers).status_code == 403
    denied = client.put(
        "/api/v1/admin/call-clocks",
        headers=headers,
        json={"intraday_btst_minutes": 30, "short_term_days": 7, "long_term_days": 30},
    )
    assert denied.status_code == 403


def test_an_admin_saves_the_three_clocks(client, db):
    session = sign_in(client, "9988776644")
    grant_admin_role(db, "9988776644")
    db.commit()
    headers = bearer(session["access_token"])
    seen = client.get("/api/v1/admin/call-clocks", headers=headers)
    assert seen.status_code == 200, seen.text
    assert seen.json() == {
        "intraday_btst_minutes": 30,
        "short_term_days": 30,
        "long_term_days": 30,
    }
    saved = client.put(
        "/api/v1/admin/call-clocks",
        headers=headers,
        json={"intraday_btst_minutes": 45, "short_term_days": 7, "long_term_days": 90},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["short_term_days"] == 7
    again = client.get("/api/v1/admin/call-clocks", headers=headers)
    assert again.json()["long_term_days"] == 90
    rejected = client.put(
        "/api/v1/admin/call-clocks",
        headers=headers,
        json={"intraday_btst_minutes": 0, "short_term_days": 7, "long_term_days": 90},
    )
    assert rejected.status_code == 422
    audit = db.scalars(
        select(AuditEvent).where(AuditEvent.action == "signals.call_clocks_saved")
    ).one()
    assert audit.payload["intraday_btst_minutes"] == 45
    assert audit.payload["short_term_days"] == 7
