"""Counts for the Fyers Data API. The access token is never included."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

logger = logging.getLogger("quantivo.quotes")

_LOCK = threading.Lock()
_HITS = 0
_MISSES = 0
_LIMITED = 0
_LOGGED_AT: datetime | None = None


def clear_meter() -> None:
    global _HITS, _MISSES, _LIMITED, _LOGGED_AT
    with _LOCK:
        _HITS = 0
        _MISSES = 0
        _LIMITED = 0
        _LOGGED_AT = None


def note_hit() -> None:
    global _HITS
    with _LOCK:
        _HITS += 1


def note_miss() -> None:
    global _MISSES
    with _LOCK:
        _MISSES += 1


def note_limited() -> None:
    global _LIMITED
    with _LOCK:
        _LIMITED += 1


def maybe_log(moment: datetime, *, history_queue: int) -> None:
    """One line a minute, with rolling counts and the history queue depth."""
    global _LOGGED_AT
    from app.modules.quotes.budget import usage

    with _LOCK:
        if _LOGGED_AT is not None and moment - _LOGGED_AT < timedelta(seconds=60):
            return
        _LOGGED_AT = moment
        hits, misses, limited = _HITS, _MISSES, _LIMITED
    counts = usage(moment)
    logger.info(
        "fyers data quotes_minute=%s history_minute=%s quotes_day=%s history_day=%s "
        "hits=%s misses=%s limited=%s history_queue=%s",
        counts["quotes_minute"],
        counts["history_minute"],
        counts["quotes_day"],
        counts["history_day"],
        hits,
        misses,
        limited,
        history_queue,
    )
