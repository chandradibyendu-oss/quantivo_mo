"""Equity posts are accepted on weekdays from 09:15 to 15:30 IST."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
_OPEN = time(9, 15)
_CLOSE = time(15, 30)


def quote_label(moment: datetime) -> str:
    """LTP while the cash session is open. Last LTP after the close and on weekends."""

    return "LTP" if in_equity_window(moment) else "Last LTP"


def session_day(moment: datetime):
    """The session the chart draws. A weekend or a pre-open morning uses the previous one."""

    local = moment.astimezone(IST)
    day = local.date()
    if local.weekday() < 5 and local.time() >= _OPEN:
        return day
    day = day - timedelta(days=1)
    while day.weekday() >= 5:
        day = day - timedelta(days=1)
    return day


def in_equity_window(sent_at: datetime) -> bool:
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=ZoneInfo("UTC"))
    local = sent_at.astimezone(IST)
    if local.weekday() >= 5:
        return False
    return _OPEN <= local.time() <= _CLOSE
