"""Shared Fyers Data API budget for this process.

Prime plan figures, as published for 16 October 2026: 10 calls a second,
500 a minute, and 500,000 a day. Quotes and History share that allowance.
History may take 450 of the minute so a quote call still has room.
A 429 pauses both. The wait starts at 30 seconds and doubles up to 15 minutes.
This process cannot see another program on the same Fyers account.
"""

from __future__ import annotations

import logging
import random
import threading
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

logger = logging.getLogger("quantivo.quotes")

DataKind = Literal["quotes", "history"]

PER_SECOND = 10
PER_MINUTE = 500
PER_DAY = 500_000
HISTORY_PER_MINUTE = 450
_PAUSE_START = 30
_PAUSE_CAP = 15 * 60
IST = ZoneInfo("Asia/Kolkata")

_LOCK = threading.Lock()
_CALLS: list[tuple[datetime, DataKind]] = []
_PAUSED_UNTIL: datetime | None = None
_STRIKES = 0


def _default_jitter() -> float:
    return random.uniform(0, 5)


_JITTER = _default_jitter


def clear_data_budget() -> None:
    global _PAUSED_UNTIL, _STRIKES
    with _LOCK:
        _CALLS.clear()
        _PAUSED_UNTIL = None
        _STRIKES = 0


def set_pause_jitter(fn) -> None:
    """Tests pin the extra wait. Production keeps a few seconds of jitter."""
    global _JITTER
    _JITTER = fn


def data_paused(moment: datetime) -> bool:
    with _LOCK:
        return _PAUSED_UNTIL is not None and moment < _PAUSED_UNTIL


def note_rate_limit(moment: datetime) -> None:
    """Back off both Data API callers. The response body is not logged."""
    global _PAUSED_UNTIL, _STRIKES
    with _LOCK:
        _STRIKES += 1
        delay = min(_PAUSE_START * (2 ** (_STRIKES - 1)), _PAUSE_CAP) + _JITTER()
        _PAUSED_UNTIL = moment + timedelta(seconds=delay)
        strikes = _STRIKES
        until = _PAUSED_UNTIL
    logger.warning(
        "Fyers data calls are paused until %s after rate limit %s",
        until.isoformat(),
        strikes,
    )


def take_data_slot(kind: DataKind, moment: datetime) -> bool:
    """Record one call when the shared allowance has room. False when it does not."""
    global _STRIKES
    with _LOCK:
        if _PAUSED_UNTIL is not None and moment < _PAUSED_UNTIL:
            return False
        _prune(moment)
        second, minute, history_minute, day = _counts(moment)
        if day >= PER_DAY or second >= PER_SECOND or minute >= PER_MINUTE:
            return False
        if kind == "history" and history_minute >= HISTORY_PER_MINUTE:
            return False
        _CALLS.append((moment, kind))
        _STRIKES = 0
        return True


def usage(moment: datetime) -> dict[str, int]:
    with _LOCK:
        _prune(moment)
        second, minute, history_minute, day = _counts(moment)
        quotes_minute = minute - history_minute
        quotes_day = sum(1 for _moment, kind in _CALLS if kind == "quotes")
        history_day = day - quotes_day
        return {
            "second": second,
            "minute": minute,
            "quotes_minute": quotes_minute,
            "history_minute": history_minute,
            "quotes_day": quotes_day,
            "history_day": history_day,
            "day": day,
        }


def _prune(moment: datetime) -> None:
    day = moment.astimezone(IST).date()
    kept = [item for item in _CALLS if item[0].astimezone(IST).date() == day]
    _CALLS[:] = kept


def _counts(moment: datetime) -> tuple[int, int, int, int]:
    second_cut = moment - timedelta(seconds=1)
    minute_cut = moment - timedelta(seconds=60)
    second = minute = history_minute = 0
    for stamped, kind in _CALLS:
        if stamped > minute_cut:
            minute += 1
            if kind == "history":
                history_minute += 1
            if stamped > second_cut:
                second += 1
    return second, minute, history_minute, len(_CALLS)
