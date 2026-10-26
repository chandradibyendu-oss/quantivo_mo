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
_SEEN: set[tuple[str, date]] = set()
_LIVE: dict[str, Bar] = {}
_QUEUE: queue.Queue[tuple[str, date]] = queue.Queue()
_QUEUED: set[tuple[str, date]] = set()
_STARTED = False
_SESSION_OPEN = 9 * 60 + 15
_SESSION_CLOSE = 15 * 60 + 30


def history_queue_depth() -> int:
    return _QUEUE.qsize()


def clear_history_cache() -> None:
    """Drop this process's copy. Saved bars stay in the database."""

    with _LOCK:
        _CACHE.clear()
        _SEEN.clear()
        _LIVE.clear()
        _QUEUED.clear()


def clear_live_minutes() -> None:
    with _LOCK:
        _LIVE.clear()


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
        stored = _recall(code, day, now)
    if stored is None:
        return "missing", []
    expired = stored.retry is not None and now - stored.fetched_at >= stored.retry
    if stored.bars is None:
        return ("missing" if expired else "failed"), []
    bars = _overlay(code, day, stored.bars)
    if expired:
        return "stale", bars
    return "ready", bars


def note_print(code: str, price: Decimal, moment: datetime) -> None:
    """Fold one socket price into the minute that is still forming.

    The finished minute is saved. The open minute stays in memory.
    """

    if price <= 0:
        return
    opened = moment.astimezone(IST).replace(second=0, microsecond=0)
    minute = opened.hour * 60 + opened.minute
    inside = opened.weekday() < 5 and _SESSION_OPEN <= minute <= _SESSION_CLOSE
    finished: Bar | None = None
    with _LOCK:
        current = _LIVE.get(code)
        if current is not None and _minute(current[0]) != opened:
            finished = current
            _LIVE.pop(code, None)
        if inside:
            if current is None or _minute(current[0]) != opened:
                _LIVE[code] = (opened, price, price, price, price)
            else:
                _LIVE[code] = (
                    opened,
                    max(current[1], price),
                    min(current[2], price),
                    price,
                    current[4] if len(current) > 4 else current[1],
                )
    if finished is not None:
        _store_finished(code, finished)


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


def _wait_for_slot() -> bool:
    """Take one History slot, waiting out a short pause. The list read does not call Fyers."""
    from app.modules.quotes.budget import data_paused, take_data_slot

    for _ in range(30):
        now = datetime.now(IST)
        if not data_paused(now) and take_data_slot("history", now):
            return True
        threading.Event().wait(1)
    return False


def _defer(code: str, day: date) -> None:
    def later() -> None:
        threading.Event().wait(5)
        with _LOCK:
            if (code, day) in _QUEUED:
                return
            _QUEUED.add((code, day))
        _QUEUE.put((code, day))

    threading.Thread(target=later, name="fyers-history-defer", daemon=True).start()


def _retain(code: str, day: date, retry: timedelta) -> None:
    """Keep bars already read. A failed refresh does not replace them with an empty day."""
    now = datetime.now(IST)
    _state, existing = day_state(code, day, now)
    remember_day(code, day, existing if existing else None, now=now, retry=retry)


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
        deferred = False
        try:
            if not _wait_for_slot():
                deferred = True
                continue
            _pull(code, day)
        except Exception:
            logger.warning("Fyers history could not be read")
            _retain(code, day, _RETRY)
        finally:
            with _LOCK:
                _QUEUED.discard((code, day))
            _QUEUE.task_done()
            if deferred:
                _defer(code, day)
            from app.modules.quotes.meter import maybe_log

            maybe_log(datetime.now(IST), history_queue=_QUEUE.qsize())


def _pull(code: str, day: date) -> None:
    from app.modules.quotes.fyers import quotes_paused
    from app.modules.quotes.session import ensure_access_token

    if quotes_paused(datetime.now(IST)):
        _retain(code, day, _RATE_LIMIT)
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
        if exc.code == 429:
            from app.modules.quotes.fyers import pause_quotes

            pause_quotes(datetime.now(IST))
        _retain(code, day, retry)
        logger.warning("Fyers history could not be read")
        return
    except OSError:
        _retain(code, day, _RETRY)
        logger.warning("Fyers history could not be read")
        return
    bars = parse_fyers_candles(body)
    if bars is None:
        _retain(code, day, _RETRY)
        logger.warning("Fyers history could not be read")
        return
    now = datetime.now(IST)
    _keep(code, day, bars, now)


def _keep(code: str, day: date, bars: list[Bar], now: datetime) -> None:
    """Remember a day that was just read, and save it. This process does not read it again."""

    from app.modules.feeds.window import in_equity_window

    complete = day < now.date() or not in_equity_window(now)
    remember_day(code, day, bars, now=now, retry=None)
    with _LOCK:
        _SEEN.add((code, day))
    if not _persist_enabled():
        return
    try:
        from app.modules.progress.bars import save_bars

        save_bars(code, day, bars, complete=complete)
    except Exception:
        logger.warning("One-minute bars could not be saved")


def _recall(code: str, day: date, now: datetime) -> _Stored | None:
    if not _persist_enabled():
        return None
    try:
        from app.modules.progress.bars import load_saved

        bars, complete = load_saved(code, day)
    except Exception:
        logger.warning("Saved one-minute bars could not be read")
        return None
    if bars is None and not complete:
        return None
    with _LOCK:
        seen = (code, day) in _SEEN
    if complete or day < now.astimezone(IST).date() or seen:
        remember_day(code, day, bars or [], now=now, retry=None)
    else:
        remember_day(
            code,
            day,
            bars or [],
            now=now - _RETRY - timedelta(seconds=1),
            retry=_RETRY,
        )
    with _LOCK:
        return _CACHE.get((code, day))


def _store_finished(code: str, bar: Bar) -> None:
    opened = _minute(bar[0])
    day = opened.date()
    with _LOCK:
        stored = _CACHE.get((code, day))
        if stored is not None and stored.bars is not None:
            kept = [item for item in stored.bars if _minute(item[0]) != opened]
            kept.append(bar)
            _CACHE[(code, day)] = _Stored(stored.fetched_at, kept, stored.retry)
    if not _persist_enabled():
        return
    try:
        from app.modules.progress.bars import save_bars

        save_bars(code, day, [bar], complete=False)
    except Exception:
        logger.warning("A finished minute could not be saved")


def _overlay(code: str, day: date, bars: list[Bar]) -> list[Bar]:
    with _LOCK:
        live = _LIVE.get(code)
    if live is None or _minute(live[0]).date() != day:
        return list(bars)
    opened = _minute(live[0])
    kept = [bar for bar in bars if _minute(bar[0]) != opened]
    kept.append(live)
    return kept


def _minute(moment: datetime) -> datetime:
    return moment.astimezone(IST).replace(second=0, microsecond=0)


def _persist_enabled() -> bool:
    return get_settings().environment != "test"


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
