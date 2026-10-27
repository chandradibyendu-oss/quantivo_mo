"""PDL Sweep rows become calls. Intraday lasts until the cash close."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.modules.feeds.models import SourceFeed
from app.modules.feeds.pdl_sweep import (
    calls_from_payload,
    desk_stars,
    outcome_guide,
    poll_http_feeds,
    visible_note,
)
from app.modules.scanners.models import Scanner, SourceChannel
from app.modules.signals.models import Signal
from app.modules.signals.status import derived_status
from sqlalchemy import select

IST = ZoneInfo("Asia/Kolkata")


def _channel(db) -> SourceChannel:
    scanner = db.scalar(select(Scanner).limit(1))
    channel = SourceChannel(
        scanner_id=scanner.id,
        code="pdl-sweep",
        name="PDL Sweep",
        segment="equity",
        horizon_aliases=[],
        status="active",
    )
    db.add(channel)
    db.flush()
    db.add(
        SourceFeed(
            source_channel_id=channel.id,
            kind="http_api",
            status="active",
            options={
                "url": "http://127.0.0.1:8000/api/watchlist/pdl-sweep/live",
                "method": "GET",
                "poll_seconds": 60,
            },
        )
    )
    db.flush()
    return channel


def _payload() -> dict:
    return {
        "session_date": "2026-10-27",
        "today": [
            {
                "symbol": "BERGEPAINT",
                "signal": "LONG",
                "trade_date": "2026-10-27",
                "signal_time": "09:20",
                "entry": "465.45",
                "stop": "428.214",
                "target": "467.8231",
                "company_name": "Berger Paints India Limited",
                "stars": 4,
                "hit_rate": "91.2",
                "history_hits": 115,
                "history_trades": 126,
            },
            {
                "symbol": "TCS",
                "signal": "SHORT",
                "horizon": "Short term",
                "trade_date": "2026-10-27",
                "signal_time": "10:05",
                "entry": "3000",
                "stop": "3100",
                "target": "2800",
            },
        ],
        "history": [
            {
                "symbol": "OLDNAME",
                "signal": "LONG",
                "trade_date": "2026-10-23",
                "signal_time": "09:20",
                "entry": "100",
                "stop": "90",
                "target": "110",
                "target_hit_date": "2026-10-23",
                "target_hit_time": "15:00",
            }
        ],
    }


def test_intraday_lasts_until_the_cash_close_and_a_sent_horizon_is_kept(db):
    channel = _channel(db)
    drafts = calls_from_payload(_payload(), channel=channel)
    assert [draft.symbol for draft in drafts] == ["BERGEPAINT", "TCS", "OLDNAME"]
    paint, tcs, old = drafts
    assert paint.horizon_raw == "Intraday"
    assert paint.side == "BUY"
    assert paint.timeframe == "INTRADAY"
    assert paint.product_hint == "MIS"
    assert paint.external_ref == "pdl:BERGEPAINT:2026-10-27:09:20"
    published = datetime(2026, 10, 27, 9, 20, tzinfo=IST)
    assert paint.published_at == published
    assert paint.expires_at == datetime(2026, 10, 27, 15, 30, tzinfo=IST)
    assert derived_status(paint, published + timedelta(minutes=31)) == "active"
    assert derived_status(paint, datetime(2026, 10, 27, 15, 30, tzinfo=IST)) == "active"
    assert derived_status(paint, datetime(2026, 10, 28, 0, 0, tzinfo=IST)) == "expired"
    assert old.expires_at == datetime(2026, 10, 23, 15, 30, tzinfo=IST)
    assert derived_status(old, published) == "expired"
    assert visible_note(old.provider_note) is None
    assert visible_note(paint.provider_note) == "Berger Paints India Limited"
    assert desk_stars(paint.provider_note) == (
        4,
        "115 of 126 reached the target within 7 days. 91% 7-day target touch rate.",
    )
    assert desk_stars(tcs.provider_note) is None
    assert outcome_guide(old.provider_note, "window_over") == (
        "final",
        "Final 15:00",
        "The last target was touched in this minute. That is the exit.",
    )
    assert outcome_guide(old.provider_note, "expired", now=published) == (
        "final",
        "Final 23 Oct 15:00",
        "The last target was touched in this minute. That is the exit.",
    )
    assert outcome_guide(paint.provider_note, "expired") is None

    assert tcs.horizon_raw == "Short term"
    assert tcs.side == "SELL"
    assert tcs.timeframe == "POSITIONAL"
    assert tcs.expires_at == datetime(2026, 10, 27, 10, 5, tzinfo=IST) + timedelta(days=30)

    mani = SimpleNamespace(
        match_status="matched",
        horizon_raw="Intraday",
        timeframe="INTRADAY",
        published_at=published,
        expires_at=published + timedelta(hours=8),
    )
    assert derived_status(mani, published + timedelta(minutes=31)) == "stale"


def test_the_worker_stores_today_and_history(db):
    channel = _channel(db)
    seen = {}

    def fetch(url, headers):
        seen["url"] = url
        seen["headers"] = headers
        return _payload()

    now = datetime(2026, 10, 27, 10, 0, tzinfo=IST)
    report = poll_http_feeds(db, fetch, now=now, last_polled={})
    assert report.created == 3
    assert seen["url"].endswith("/api/watchlist/pdl-sweep/live")
    assert seen["headers"] == {}
    symbols = set(db.scalars(select(Signal.symbol).where(Signal.source_channel_id == channel.id)))
    assert symbols == {"BERGEPAINT", "TCS", "OLDNAME"}

    held = {channel_feed_id(db): now}
    again = poll_http_feeds(db, fetch, now=now + timedelta(seconds=30), last_polled=held)
    assert again.created == 0
    assert again.unchanged == 0

    later = poll_http_feeds(db, fetch, now=now + timedelta(seconds=60), last_polled={})
    assert later.unchanged == 3


def channel_feed_id(db):
    feed = db.scalar(select(SourceFeed).where(SourceFeed.kind == "http_api"))
    return feed.id
