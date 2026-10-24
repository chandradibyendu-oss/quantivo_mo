from sqlalchemy import select

from app.modules.audit.models import AuditEvent
from app.modules.identity.models import User
from tests.helpers import bearer, sign_in


def test_development_otp_creates_a_session_and_does_not_audit_the_code(client, db):
    requested = client.post("/api/v1/auth/otp/request", json={"phone": "98765 43210"})
    assert requested.status_code == 200, requested.text
    body = requested.json()
    assert body["delivery"] == "dev_mock"
    assert len(body["dev_otp"]) == 6

    verified = client.post(
        "/api/v1/auth/otp/verify",
        json={
            "phone": "+91 9876543210",
            "challenge_id": body["challenge_id"],
            "otp": body["dev_otp"],
        },
    )
    assert verified.status_code == 200, verified.text
    me = client.get("/api/v1/me", headers=bearer(verified.json()["access_token"]))
    assert me.status_code == 200
    assert me.json()["phone_e164"] == "+919876543210"
    assert me.json()["roles"] == ["user"]

    db.rollback()
    audits = db.scalars(select(AuditEvent)).all()
    serialized = " ".join(str(event.payload) for event in audits)
    assert body["dev_otp"] not in serialized


def test_invalid_phone_and_wrong_code(client):
    invalid = client.post("/api/v1/auth/otp/request", json={"phone": "12345"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_phone"

    requested = client.post("/api/v1/auth/otp/request", json={"phone": "9123456789"})
    otp = requested.json()["dev_otp"]
    wrong = "000000" if otp != "000000" else "111111"
    for _ in range(5):
        rejected = client.post(
            "/api/v1/auth/otp/verify",
            json={"phone": "9123456789", "challenge_id": requested.json()["challenge_id"], "otp": wrong},
        )
        assert rejected.status_code == 401
        assert rejected.json()["error"]["code"] == "invalid_otp"
    exhausted = client.post(
        "/api/v1/auth/otp/verify",
        json={"phone": "9123456789", "challenge_id": requested.json()["challenge_id"], "otp": otp},
    )
    assert exhausted.status_code == 401


def test_otp_requests_are_rate_limited(client):
    statuses = [
        client.post("/api/v1/auth/otp/request", json={"phone": "9000000001"}).status_code for _ in range(6)
    ]
    assert statuses[:5] == [200, 200, 200, 200, 200]
    assert statuses[5] == 429


def test_refresh_rotates_and_logout_ends_the_session(client):
    first = sign_in(client, "9000000002")
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["access_token"] != first["access_token"]
    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reused.status_code == 401

    current = refreshed.json()
    logout = client.post("/api/v1/auth/logout", headers=bearer(current["access_token"]))
    assert logout.status_code == 204
    me = client.get("/api/v1/me", headers=bearer(current["access_token"]))
    assert me.status_code == 401


def test_suspended_account_cannot_get_a_new_session(client, db):
    sign_in(client, "9000000003")
    db.rollback()
    user = db.scalar(select(User).where(User.phone_e164 == "+919000000003"))
    user.status = "suspended"
    db.commit()

    requested = client.post("/api/v1/auth/otp/request", json={"phone": "9000000003"})
    rejected = client.post(
        "/api/v1/auth/otp/verify",
        json={
            "phone": "9000000003",
            "challenge_id": requested.json()["challenge_id"],
            "otp": requested.json()["dev_otp"],
        },
    )
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "account_unavailable"
