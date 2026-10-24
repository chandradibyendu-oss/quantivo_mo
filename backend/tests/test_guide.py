from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.modules.signals.status import guide_for

IST = timezone(timedelta(hours=5, minutes=30))


def _call(**kwargs):
    values = {
        "match_status": "matched",
        "status": "active",
        "timeframe": "POSITIONAL",
        "published_at": datetime(2026, 10, 23, 10, 0, tzinfo=IST),
        "expires_at": datetime(2026, 11, 22, 10, 0, tzinfo=IST),
    }
    values.update(kwargs)
    return SimpleNamespace(**values)


def test_the_window_is_open_until_thirty_minutes_or_the_close():
    sent = datetime(2026, 10, 23, 10, 0, tzinfo=IST)
    fresh = _call(published_at=sent)
    assert guide_for(fresh, sent + timedelta(minutes=29))[0] == "waiting"
    assert guide_for(fresh, sent + timedelta(minutes=30))[0] == "window_over"

    late = _call(published_at=datetime(2026, 10, 23, 15, 20, tzinfo=IST))
    assert guide_for(late, datetime(2026, 10, 23, 15, 29, tzinfo=IST))[0] == "waiting"
    assert guide_for(late, datetime(2026, 10, 23, 15, 30, tzinfo=IST))[0] == "window_over"


def test_a_blocked_call_keeps_its_own_cue():
    now = datetime(2026, 10, 23, 11, 0, tzinfo=IST)
    still_open = _call(
        timeframe="INTRADAY",
        horizon_raw="Intraday",
        published_at=now - timedelta(minutes=29),
    )
    assert guide_for(still_open, now)[0] == "waiting"
    stale = _call(
        timeframe="INTRADAY",
        horizon_raw="BTST",
        published_at=now - timedelta(minutes=30),
    )
    assert guide_for(stale, now)[:2] == ("stale", "Stale")
    short = _call(
        horizon_raw="Short term",
        published_at=now - timedelta(days=30),
        expires_at=now + timedelta(days=1),
    )
    assert guide_for(short, now)[0] == "stale"
    held = _call(
        horizon_raw="Long term",
        published_at=now - timedelta(days=29),
        expires_at=now + timedelta(days=1),
    )
    assert guide_for(held, now)[0] == "window_over"
    week = _call(
        horizon_raw="Intraday to 7 days",
        published_at=now - timedelta(minutes=45),
    )
    assert guide_for(week, now)[0] == "window_over"
    stored_word = _call(status="withdrawn")
    assert guide_for(stored_word, now)[0] == "window_over"
    stored_expiry = _call(status="expired", expires_at=now + timedelta(days=1))
    assert guide_for(stored_expiry, now)[0] == "window_over"
    clock_expiry = _call(expires_at=now - timedelta(minutes=1))
    assert guide_for(clock_expiry, now)[0] == "expired"
    unnamed = _call(match_status="unmatched")
    assert guide_for(unnamed, now)[:2] == ("no_symbol", "No NSE")
