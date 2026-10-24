"""How long each horizon stays actionable. One saved row, read when a call is shown."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

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
    """The age that marks this horizon stale. Other horizons use expiry only."""

    raw = str(getattr(signal, "horizon_raw", "") or "")
    key = " ".join(raw.strip().lower().replace("-", " ").split())
    if key.startswith("short"):
        return timedelta(days=clocks.short_term_days)
    if key.startswith("long"):
        return timedelta(days=clocks.long_term_days)
    if session_horizon(raw) or (not key and getattr(signal, "timeframe", "") == "INTRADAY"):
        return timedelta(minutes=clocks.intraday_minutes)
    return None
