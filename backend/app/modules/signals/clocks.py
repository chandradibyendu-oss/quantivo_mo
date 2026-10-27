"""How long each horizon stays actionable. One saved row, read when a call is shown."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.modules.feeds.equity_parser import session_horizon
from app.modules.signals.models import CallClock


@dataclass(frozen=True)
class CallClocks:
    intraday_minutes: int = 30
    short_term_days: int = 30
    long_term_days: int = 30


def load_clocks(db: Session) -> CallClocks:
    row = db.get(CallClock, 1)
    if row is None:
        return CallClocks()
    return CallClocks(row.intraday_minutes, row.short_term_days, row.long_term_days)


def save_clocks(db: Session, clocks: CallClocks) -> CallClocks:
    row = db.get(CallClock, 1)
    if row is None:
        row = CallClock(
            id=1,
            intraday_minutes=clocks.intraday_minutes,
            short_term_days=clocks.short_term_days,
            long_term_days=clocks.long_term_days,
        )
        db.add(row)
    else:
        row.intraday_minutes = clocks.intraday_minutes
        row.short_term_days = clocks.short_term_days
        row.long_term_days = clocks.long_term_days
    db.flush()
    return clocks


def stale_window(signal, clocks: CallClocks) -> timedelta | None:
    """The age that marks this horizon stale. Other horizons use expiry only.

    A same-day call that expires at 15:30 IST stays on Actionable through that
    IST date. The 30-minute clock remains for a same-day call with a different expiry.
    """

    raw = str(getattr(signal, "horizon_raw", "") or "")
    key = " ".join(raw.strip().lower().replace("-", " ").split())
    if key.startswith("short"):
        return timedelta(days=clocks.short_term_days)
    if key.startswith("long"):
        return timedelta(days=clocks.long_term_days)
    if session_horizon(raw) or (not key and getattr(signal, "timeframe", "") == "INTRADAY"):
        if _expires_at_cash_close(signal):
            return None
        return timedelta(minutes=clocks.intraday_minutes)
    return None


def _as_ist(value):
    zone = ZoneInfo("Asia/Kolkata")
    if value.tzinfo is None:
        return value.replace(tzinfo=zone)
    return value.astimezone(zone)


def still_tracking(signal, now) -> bool:
    """A desk call that expires at the cash close stays on Actionable through that IST date."""

    if not _expires_at_cash_close(signal):
        return False
    published = getattr(signal, "published_at", None)
    if published is None:
        return False
    return _as_ist(now).date() == _as_ist(published).date()


def _expires_at_cash_close(signal) -> bool:
    expires = getattr(signal, "expires_at", None)
    published = getattr(signal, "published_at", None)
    if expires is None or published is None:
        return False
    end = _as_ist(expires)
    start = _as_ist(published)
    return (
        end.hour == 15
        and end.minute == 30
        and end.second == 0
        and end.microsecond == 0
        and end.date() == start.date()
    )
