"""One-minute NSE cash bars from Fyers. The app id and token stay in the environment."""

from __future__ import annotations

import json
import logging
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.core.config import get_settings

logger = logging.getLogger("quantivo.history")

FYERS_HISTORY_URL = "https://api-t1.fyers.in/data/history"
IST = ZoneInfo("Asia/Kolkata")
_TIMEOUT_SECONDS = 4
_RETRY = timedelta(seconds=60)
_RATE_LIMIT = timedelta(minutes=15)

Bar = tuple[datetime, Decimal, Decimal, Decimal]


@dataclass
class _Stored:
    fetched_at: datetime
    bars: list[Bar] | None
    retry: timedelta | None


_LOCK = threading.Lock()
_CACHE: dict[tuple[str, date], _Stored] = {}
_QUEUE: queue.Queue[tuple[str, date]] = queue.Queue()
_QUEUED: set[tuple[str, date]] = set()
_STARTED = False


def clear_history_cache() -> None:
    with _LOCK:
        _CACHE.clear()
        _QUEUED.clear()


def parse_fyers_candles(body: str) -> list[Bar] | None:
    """Closed-bar fields from a Fyers history payload. None means the payload is not usable."""

    try:
        payload = json.loads(body, parse_float=Decimal)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("s") != "ok":
        return None
    candles = payload.get("candles")
    if not isinstance(candles, list):
        return None
    bars: list[Bar] = []
    for row in candles:
        if not isinstance(row, list) or len(row) < 5:
            continue
        opened = datetime.fromtimestamp(int(row[0]), IST)
        bars.append(
            (opened, Decimal(row[2]), Decimal(row[3]), Decimal(row[4]), Decimal(row[1]))
        )
    return bars


def remember_day(
    code: str,
    day: date,
    bars: list[Bar] | None,
    *,
    now: datetime,
    retry: timedelta | None,
) -> None:
    with _LOCK:
        _CACHE[(code, day)] = _Stored(now, bars, retry)


def day_state(code: str, day: date, now: datetime) -> tuple[str, list[Bar]]:
    """ready, stale, missing, or failed. Stale still returns the previous bars."""

    with _LOCK:
        stored = _CACHE.get((code, day))
    if stored is None:
        return "missing", []
    expired = stored.retry is not None and now - stored.fetched_at >= stored.retry
    if stored.bars is None:
        return ("missing" if expired else "failed"), []
    if expired:
        return "stale", stored.bars
    return "ready", stored.bars


def request_day(code: str, day: date, *, budget: list[int]) -> bool:
    """Ask the background reader for one day. False when this request's budget is spent."""

    key = (code, day)
    with _LOCK:
        if key in _QUEUED:
            return True
        if budget[0] <= 0:
            return False
        budget[0] -= 1
        _QUEUED.add(key)
    _QUEUE.put(key)
    _start()
    return True


def _start() -> None:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
    thread = threading.Thread(target=_loop, name="fyers-history", daemon=True)
    thread.start()


def _loop() -> None:
    while True:
        code, day = _QUEUE.get()
        try:
            _pull(code, day)
        except Exception:
            logger.warning("Fyers history could not be read")
            remember_day(code, day, None, now=datetime.now(IST), retry=_RETRY)
        finally:
            with _LOCK:
                _QUEUED.discard((code, day))
            _QUEUE.task_done()
            threading.Event().wait(0.25)


def _pull(code: str, day: date) -> None:
    from app.modules.quotes.fyers import quotes_paused
    from app.modules.quotes.session import ensure_access_token

    if quotes_paused(datetime.now(IST)):
        remember_day(code, day, None, now=datetime.now(IST), retry=_RATE_LIMIT)
        return
    ensure_access_token()
    settings = get_settings()
    app_id = settings.fyers_app_id.strip()
    token = settings.fyers_access_token.strip()
    if not app_id or not token:
        return
    query = urllib.parse.urlencode(
        {
            "symbol": code,
            "resolution": "1",
            "date_format": "1",
            "range_from": day.isoformat(),
            "range_to": day.isoformat(),
            "cont_flag": "1",
        }
    )
    # urlencode encodes the colon. Fyers accepts the code with the colon left as-is.
    query = query.replace("NSE%3A", "NSE:", 1)
    try:
        body = _open(f"{FYERS_HISTORY_URL}?{query}", f"{app_id}:{token}")
    except urllib.error.HTTPError as exc:
        exc.read()
        retry = _RATE_LIMIT if exc.code == 429 else _RETRY
        remember_day(code, day, None, now=datetime.now(IST), retry=retry)
        logger.warning("Fyers history could not be read")
        return
    except OSError:
        remember_day(code, day, None, now=datetime.now(IST), retry=_RETRY)
        logger.warning("Fyers history could not be read")
        return
    bars = parse_fyers_candles(body)
    if bars is None:
        remember_day(code, day, None, now=datetime.now(IST), retry=_RETRY)
        logger.warning("Fyers history could not be read")
        return
    today = datetime.now(IST).date()
    retry = _RETRY if day >= today else None
    remember_day(code, day, bars, now=datetime.now(IST), retry=retry)


def _open(url: str, authorization: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"Authorization": authorization, "User-Agent": "Quantivo/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        exc.read()
        raise
