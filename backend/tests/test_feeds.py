from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.grant_admin import grant_admin_role
from app.modules.audit.models import AuditEvent
from app.modules.feeds.equity_directory import EquityDirectory, EquityRecord
from app.modules.feeds.equity_parser import continue_equity_call, parse_equity_call, realistic_stop
from app.modules.feeds.normalize import _expires_at, rematch_channel_names
from app.modules.feeds.service import ChannelPost, poll_telegram_feeds
from app.modules.scanners.models import SourceChannel
from app.modules.signals.models import Signal
from app.modules.signals.status import derived_status, is_executable
from sqlalchemy import select
from tests.helpers import bearer, sign_in

_POST = """Intraday to 7 days
RELIANCE above 2450
SL 2432
Targets 2474 2490
"""

_INTRADAY = """Intraday
TCS above 4100
SL 4050
Targets 4200
"""


def test_parser_keeps_published_horizon_words():
    parsed = parse_equity_call(_POST)
    assert parsed is not None
    assert parsed.horizon_raw == "Intraday to 7 days"
    assert parsed.name_raw == "RELIANCE"
    assert parsed.buy_above == Decimal("2450")
    assert parsed.stop_loss == Decimal("2432")
    assert parsed.targets == (Decimal("2474"), Decimal("2490"))

    other = parse_equity_call(_INTRADAY)
    assert other is not None
    assert other.horizon_raw == "Intraday"
    assert other.horizon_raw != "Intraday to 7 days"


def test_intraday_to_seven_days_expires_after_seven_days():
    published = datetime(2026, 10, 16, 6, 47, tzinfo=UTC)
    assert _expires_at("Intraday to 7 days", published) == published + timedelta(days=7)
    assert _expires_at("INTARDAY TO 7 DAYS.", published) == published + timedelta(days=7)
    assert _expires_at("Intraday", published) == published + timedelta(hours=8)
    assert _expires_at("Short term", published) == published + timedelta(days=30)
    assert _expires_at("Intraday or 1-3 days", published) == published + timedelta(days=30)


def test_parser_drops_a_post_without_a_target_and_corrects_a_long_stop():
    assert parse_equity_call("RELIANCE above 2450\nSL 2432\n") is None
    assert realistic_stop(Decimal("700"), Decimal("6500")) == Decimal("650")
    assert realistic_stop(Decimal("1005"), Decimal("1030")) == Decimal("1030")


def test_a_last_target_below_the_buy_gains_the_missing_zero():
    parsed = parse_equity_call("BUY RICOAUTO ABOVE 114\nSL 99.15\nTARGETS 120....36+")
    assert parsed is not None
    assert parsed.buy_above == Decimal("114")
    assert parsed.stop_loss == Decimal("99.15")
    assert parsed.targets == (Decimal("120"), Decimal("360"))
    from app.modules.feeds.equity_parser import align_prices

    trigger, stop, targets = align_prices(
        "BUY",
        Decimal("114"),
        Decimal("99.15"),
        [Decimal("120"), Decimal("36")],
        Decimal("99.92"),
    )
    assert trigger == Decimal("114")
    assert stop == Decimal("99.15")
    assert targets == [Decimal("120"), Decimal("360")]
    kept = align_prices(
        "BUY",
        Decimal("114"),
        Decimal("99.15"),
        [Decimal("120"), Decimal("360")],
        Decimal("99.92"),
    )
    assert kept[2] == [Decimal("120"), Decimal("360")]


_SG_OPENING = """INTRADAY TO 7 DAYS

BUY SG MART ABOVE 806

TARGETS 830....850+
"""


def test_the_next_message_can_supply_a_missing_stop():
    parsed = continue_equity_call(_SG_OPENING, "SL 770")
    assert parsed is not None
    assert parsed.horizon_raw == "INTRADAY TO 7 DAYS"
    assert parsed.name_raw == "SG MART"
    assert parsed.buy_above == Decimal("806")
    assert parsed.stop_loss == Decimal("770")
    assert parsed.targets == (Decimal("830"), Decimal("850"))
    assert continue_equity_call(_SG_OPENING, _POST) is None
    assert continue_equity_call(_POST, "SL 770") is None
    filled = continue_equity_call(
        "INTRADAY TO 7 DAYS\nBUY SG MART ABOVE 806\nSL 770\n",
        "TARGETS 830....850+",
    )
    assert filled is not None
    assert filled.targets == (Decimal("830"), Decimal("850"))
    assert filled.stop_loss == Decimal("770")


def test_trader_cannot_change_feed_settings(client):
    session = sign_in(client)
    denied = client.get(
        "/api/v1/admin/source-channels",
        headers=bearer(session["access_token"]),
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"
    login = client.get(
        "/api/v1/admin/telegram-login",
        headers=bearer(session["access_token"]),
    )
    assert login.status_code == 403
    lookup = client.post(
        "/api/v1/admin/telegram-channels/lookup",
        headers=bearer(session["access_token"]),
        json={"name": "Equity Premium SEBI Reg"},
    )
    assert lookup.status_code == 403


def test_operator_sees_the_shared_telegram_login_without_its_values(client, db):
    session = sign_in(client, "9988776611")
    grant_admin_role(db, "9988776611")
    db.commit()
    seen = client.get(
        "/api/v1/admin/telegram-login",
        headers=bearer(session["access_token"]),
    )
    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert body["status"] == "missing"
    assert "api_hash" not in seen.text
    assert "api_id" not in seen.text


def test_operator_looks_up_a_joined_channel_by_name(client, db, monkeypatch):
    session = sign_in(client, "9988776633")
    grant_admin_role(db, "9988776633")
    db.commit()
    headers = bearer(session["access_token"])

    short = client.post(
        "/api/v1/admin/telegram-channels/lookup",
        headers=headers,
        json={"name": "ab"},
    )
    assert short.status_code == 422

    async def fake_lookup(name: str):
        from app.modules.feeds.telegram_source import JoinedChannel

        assert "equity premium" in name.lower()
        return [JoinedChannel("-1001924273800", "Equity Premium SEBI Reg.")]

    monkeypatch.setattr("app.modules.feeds.router.find_joined_channels", fake_lookup)
    found = client.post(
        "/api/v1/admin/telegram-channels/lookup",
        headers=headers,
        json={"name": "Equity Premium SEBI Reg"},
    )
    assert found.status_code == 200, found.text
    body = found.json()
    match = {"channel_id": "-1001924273800", "title": "Equity Premium SEBI Reg."}
    assert body["matches"] == [match]
    assert "api_hash" not in found.text


def test_operator_saves_telegram_and_http_settings_without_secrets(client, db):
    session = sign_in(client, "9988776655")
    grant_admin_role(db, "9988776655")
    db.commit()
    headers = bearer(session["access_token"])

    listed = client.get("/api/v1/admin/source-channels", headers=headers)
    assert listed.status_code == 200, listed.text
    equity = listed.json()[0]
    assert equity["channel_code"] == "equity"
    assert equity["kind"] == "none"
    assert equity["reader"]["state"] == "sample"
    channel_id = equity["channel_id"]

    saved = client.put(
        f"/api/v1/admin/source-channels/{channel_id}/feed",
        headers=headers,
        json={
            "kind": "telegram",
            "status": "active",
            "options": {
                "channel_id": "-1001234567890",
                "parser": "equity_calls",
                "poll_limit": 20,
            },
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["kind"] == "telegram"
    assert body["options"]["channel_id"] == "-1001234567890"
    assert body["reader"]["state"] == "login_not_configured"
    assert set(body["options"]) == {"channel_id", "parser", "poll_limit"}

    rejected = client.put(
        f"/api/v1/admin/source-channels/{channel_id}/feed",
        headers=headers,
        json={
            "kind": "telegram",
            "options": {
                "channel_id": "-1001234567890",
                "parser": "equity_calls",
                "api_hash": "nope",
            },
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "feed_secret_rejected"

    http = client.put(
        f"/api/v1/admin/source-channels/{channel_id}/feed",
        headers=headers,
        json={
            "kind": "http_api",
            "options": {
                "url": "https://feeds.example.test/calls",
                "poll_seconds": 60,
                "auth_env": "MARKET_FEED_KEY",
            },
        },
    )
    assert http.status_code == 200, http.text
    assert http.json()["reader"]["state"] == "saved"
    assert http.json()["options"]["auth_env"] == "MARKET_FEED_KEY"
    assert "MARKET_FEED_KEY" not in http.json()["reader"]["detail"]

    secret_url = client.put(
        f"/api/v1/admin/source-channels/{channel_id}/feed",
        headers=headers,
        json={"kind": "http_api", "options": {"url": "https://user:pass@feeds.example.test/calls"}},
    )
    assert secret_url.status_code == 422
    assert secret_url.json()["error"]["code"] == "feed_secret_rejected"

    db.rollback()
    audits = db.scalars(select(AuditEvent).where(AuditEvent.action == "feed.configured")).all()
    serialized = " ".join(str(event.payload) for event in audits)
    assert "api_hash" not in serialized
    assert "pass" not in serialized


def test_worker_ingests_a_matched_call_and_skips_when_login_is_absent(client, db):
    session = sign_in(client, "9988776655")
    grant_admin_role(db, "9988776655")
    db.commit()
    headers = bearer(session["access_token"])
    listed = client.get("/api/v1/admin/source-channels", headers=headers)
    channel_id = listed.json()[0]["channel_id"]
    saved = client.put(
        f"/api/v1/admin/source-channels/{channel_id}/feed",
        headers=headers,
        json={
            "kind": "telegram",
            "options": {"channel_id": "-1001234567890", "parser": "equity_calls"},
        },
    )
    assert saved.status_code == 200, saved.text

    def fail_if_called(_channel_id: str, _limit: int):
        raise AssertionError("fetch must not run without a worker login")

    db.expire_all()
    skipped = poll_telegram_feeds(db, fail_if_called)
    assert skipped.login == "not_configured"
    assert skipped.created == 0

    sent_at = datetime(2026, 10, 22, 5, 0, tzinfo=UTC)
    posts = [
        ChannelPost("-1001234567890", 41, sent_at, _POST),
        ChannelPost(
            "-1001234567890",
            42,
            sent_at,
            "Short term\nHDFC Bank above 1650\nSL 1635\nTargets 1700\n",
        ),
        ChannelPost("-1001234567890", 43, datetime(2026, 10, 24, 5, 0, tzinfo=UTC), _POST),
    ]

    def fetch(channel_id: str, limit: int):
        assert channel_id == "-1001234567890"
        assert limit == 40
        return posts

    report = poll_telegram_feeds(db, fetch, login_ready=True)
    assert report.login == "used"
    assert report.created == 2
    assert report.skipped == 1
    db.commit()

    reliance = db.scalar(select(Signal).where(Signal.external_ref == "-1001234567890:41"))
    assert reliance is not None
    assert reliance.horizon_raw == "Intraday to 7 days"
    assert reliance.symbol == "RELIANCE"
    assert reliance.match_status == "matched"
    assert reliance.timeframe == "POSITIONAL"
    assert is_executable(derived_status(reliance, sent_at))

    bank = db.scalar(select(Signal).where(Signal.external_ref == "-1001234567890:42"))
    assert bank is not None
    assert bank.match_status == "unmatched"
    assert bank.horizon_raw == "Short term"
    assert not is_executable(derived_status(bank, sent_at))

    again = poll_telegram_feeds(db, fetch, login_ready=True)
    assert again.created == 0
    assert again.unchanged == 2


def test_rematch_replaces_a_stored_company_name_with_the_nse_symbol(client, db, monkeypatch):
    session = sign_in(client, "9988776644")
    grant_admin_role(db, "9988776644")
    db.commit()
    headers = bearer(session["access_token"])
    listed = client.get("/api/v1/admin/source-channels", headers=headers)
    channel_id = listed.json()[0]["channel_id"]
    saved = client.put(
        f"/api/v1/admin/source-channels/{channel_id}/feed",
        headers=headers,
        json={
            "kind": "telegram",
            "options": {"channel_id": "-1001234567890", "parser": "equity_calls"},
        },
    )
    assert saved.status_code == 200, saved.text
    sent_at = datetime(2026, 10, 22, 5, 0, tzinfo=UTC)

    def fetch(_channel_id: str, _limit: int):
        return [
            ChannelPost(
                "-1001234567890",
                51,
                sent_at,
                "Short term\nHDFC Bank above 1650\nSL 1635\nTargets 1700\n",
            )
        ]

    report = poll_telegram_feeds(db, fetch, login_ready=True)
    assert report.created == 1
    db.commit()
    stored = db.scalar(select(Signal).where(Signal.external_ref == "-1001234567890:51"))
    assert stored is not None
    assert stored.match_status == "unmatched"

    directory = EquityDirectory([EquityRecord("HDFCBANK", "HDFC Bank Limited", "EQ")])
    monkeypatch.setattr("app.modules.feeds.normalize.get_equity_directory", lambda: directory)
    assert rematch_channel_names(db) == 1
    db.commit()
    db.refresh(stored)
    assert stored.symbol == "HDFCBANK"
    assert stored.match_status == "matched"
    assert is_executable(derived_status(stored, sent_at))
    stored.provider_note = "target_hit=2026-10-22 10:20"
    db.commit()
    assert rematch_channel_names(db) == 0
    db.refresh(stored)
    assert stored.provider_note == "target_hit=2026-10-22 10:20"


def test_equity_parser_is_refused_for_a_non_equity_channel(client, db):
    session = sign_in(client, "9988776600")
    grant_admin_role(db, "9988776600")
    db.commit()
    channel = db.scalar(select(SourceChannel).where(SourceChannel.code == "equity"))
    assert channel is not None
    channel.segment = "fno"
    db.commit()
    denied = client.put(
        f"/api/v1/admin/source-channels/{channel.id}/feed",
        headers=bearer(session["access_token"]),
        json={
            "kind": "telegram",
            "options": {"channel_id": "-1001234567890", "parser": "equity_calls"},
        },
    )
    assert denied.status_code == 422
    assert denied.json()["error"]["code"] == "segment_parser_mismatch"


def test_telegram_feed_hides_sample_calls_and_reads_history_once(client, db):
    tokens = sign_in(client, "9988776622")
    headers = bearer(tokens["access_token"])
    catalogue = client.get("/api/v1/scanners", headers=headers)
    scanner_id = catalogue.json()[0]["id"]
    activated = client.post(f"/api/v1/scanners/{scanner_id}/activate", headers=headers)
    assert activated.status_code == 200
    assert client.post("/api/v1/dev/mock-feed/sync", headers=headers).status_code == 200

    grant_admin_role(db, "9988776622")
    db.commit()
    listed = client.get("/api/v1/admin/source-channels", headers=headers)
    channel_id = listed.json()[0]["channel_id"]
    saved = client.put(
        f"/api/v1/admin/source-channels/{channel_id}/feed",
        headers=headers,
        json={
            "kind": "telegram",
            "options": {"channel_id": "-1001234567890", "parser": "equity_calls"},
        },
    )
    assert saved.status_code == 200, saved.text

    closed = client.post("/api/v1/dev/mock-feed/sync", headers=headers)
    assert closed.status_code == 409
    assert closed.json()["error"]["code"] == "sample_feed_closed"

    hidden = client.get("/api/v1/signals?view=all", headers=headers)
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["feed_mode"] == "telegram_pending"
    assert hidden.json()["signals"] == []

    sent_at = datetime(2026, 10, 22, 5, 0, tzinfo=UTC)
    calls = {"history": 0, "recent": 0}

    def fetch_history(channel_ref: str, take) -> None:
        calls["history"] += 1
        assert channel_ref == "-1001234567890"
        take([ChannelPost(channel_ref, 41, sent_at, _POST)])

    def fetch(channel_ref: str, limit: int):
        calls["recent"] += 1
        assert limit == 40
        return []

    db.expire_all()
    first = poll_telegram_feeds(db, fetch, fetch_history=fetch_history, login_ready=True)
    assert first.created == 1
    assert calls == {"history": 1, "recent": 0}
    db.commit()

    shown = client.get("/api/v1/signals?view=all", headers=headers)
    assert shown.status_code == 200, shown.text
    assert len(shown.json()["signals"]) == 1
    assert shown.json()["signals"][0]["horizon_raw"] == "Intraday to 7 days"

    db.expire_all()
    second = poll_telegram_feeds(db, fetch, fetch_history=fetch_history, login_ready=True)
    assert second.created == 0
    assert calls == {"history": 1, "recent": 1}


def test_a_missing_stop_is_read_from_the_immediate_next_message(client, db):
    session = sign_in(client, "9988776611")
    grant_admin_role(db, "9988776611")
    db.commit()
    headers = bearer(session["access_token"])
    listed = client.get("/api/v1/admin/source-channels", headers=headers)
    channel_id = listed.json()[0]["channel_id"]
    saved = client.put(
        f"/api/v1/admin/source-channels/{channel_id}/feed",
        headers=headers,
        json={
            "kind": "telegram",
            "options": {"channel_id": "-1001234567890", "parser": "equity_calls"},
        },
    )
    assert saved.status_code == 200, saved.text

    sent_at = datetime(2026, 10, 26, 4, 30, tzinfo=UTC)
    opening = "Short term\nHDFC Bank above 1650\nTargets 1700\n"
    posts = [
        ChannelPost("-1001234567890", 70, sent_at, _SG_OPENING),
        ChannelPost("-1001234567890", 71, sent_at + timedelta(minutes=1), "SL 770"),
        ChannelPost("-1001234567890", 80, sent_at + timedelta(minutes=2), opening),
        ChannelPost("-1001234567890", 81, sent_at + timedelta(minutes=3), _POST),
        ChannelPost("-1001234567890", 90, sent_at + timedelta(minutes=4), _SG_OPENING),
        ChannelPost("-1001234567890", 92, sent_at + timedelta(minutes=5), "SL 770"),
        ChannelPost("-1001234567890", 100, sent_at + timedelta(minutes=6), _SG_OPENING),
        ChannelPost("-1001234567890", 101, sent_at + timedelta(minutes=20), "SL 770"),
    ]

    def fetch(_channel_id: str, _limit: int):
        return posts

    report = poll_telegram_feeds(db, fetch, login_ready=True)
    assert report.created == 2
    assert report.skipped == 6
    db.commit()

    stored = db.scalar(select(Signal).where(Signal.external_ref == "-1001234567890:70"))
    assert stored is not None
    assert stored.horizon_raw == "INTRADAY TO 7 DAYS"
    assert stored.trigger_price == Decimal("806")
    assert stored.stop_loss == Decimal("770")
    assert stored.targets == [
        {"label": "T1", "price": "830"},
        {"label": "T2", "price": "850"},
    ]
    assert db.scalar(select(Signal).where(Signal.external_ref == "-1001234567890:71")) is None
    reliance = db.scalar(select(Signal).where(Signal.external_ref == "-1001234567890:81"))
    assert reliance is not None
    assert reliance.symbol == "RELIANCE"
    assert db.scalar(select(Signal).where(Signal.external_ref == "-1001234567890:80")) is None
    assert db.scalar(select(Signal).where(Signal.external_ref == "-1001234567890:90")) is None
    assert db.scalar(select(Signal).where(Signal.external_ref == "-1001234567890:100")) is None

    again = poll_telegram_feeds(db, fetch, login_ready=True)
    assert again.created == 0
    assert again.unchanged == 2


def test_history_joins_a_stop_that_arrived_in_the_newer_batch(client, db):
    session = sign_in(client, "9988776612")
    grant_admin_role(db, "9988776612")
    db.commit()
    headers = bearer(session["access_token"])
    listed = client.get("/api/v1/admin/source-channels", headers=headers)
    channel_id = listed.json()[0]["channel_id"]
    saved = client.put(
        f"/api/v1/admin/source-channels/{channel_id}/feed",
        headers=headers,
        json={
            "kind": "telegram",
            "options": {"channel_id": "-1001234567890", "parser": "equity_calls"},
        },
    )
    assert saved.status_code == 200, saved.text
    sent_at = datetime(2026, 10, 26, 4, 30, tzinfo=UTC)

    def fetch(_channel_id: str, _limit: int):
        return []

    def fetch_history(_channel_ref: str, take) -> None:
        take([ChannelPost("-1001234567890", 71, sent_at + timedelta(minutes=1), "SL 770")])
        take([ChannelPost("-1001234567890", 70, sent_at, _SG_OPENING)])

    report = poll_telegram_feeds(db, fetch, fetch_history=fetch_history, login_ready=True)
    assert report.created == 1
    assert report.skipped == 1
    db.commit()
    stored = db.scalar(select(Signal).where(Signal.external_ref == "-1001234567890:70"))
    assert stored is not None
    assert stored.stop_loss == Decimal("770")


def test_the_channel_is_checked_every_five_seconds_while_the_window_is_open():
    from zoneinfo import ZoneInfo

    from app.modules.feeds.worker import pause_seconds

    ist = ZoneInfo("Asia/Kolkata")
    assert pause_seconds(datetime(2026, 10, 23, 10, 0, tzinfo=ist)) == 5
    assert pause_seconds(datetime(2026, 10, 23, 16, 0, tzinfo=ist)) == 60
    assert pause_seconds(datetime(2026, 10, 24, 10, 0, tzinfo=ist)) == 60
