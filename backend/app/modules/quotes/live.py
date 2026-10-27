"""One Fyers Data Socket for last traded price.

Full symbol updates carry the move against the previous close. Lite Mode does
not, so it is not used. The phone never opens this socket. A quiet symbol falls
back to the quote call. The socket starts only outside the test environment.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.modules.quotes.fyers import QuotePrint, quote_anchor

logger = logging.getLogger("quantivo.quotes")

_FRESH = timedelta(seconds=30)
_SYMBOL_CAP = 100
_TICK_BAND = Decimal("0.25")
_LOCK = threading.Lock()
_BOOK: dict[str, tuple[datetime, QuotePrint]] = {}
_WANTED: set[str] = set()
_STARTED = False
_MISSING_PACKAGE = False


def clear_live() -> None:
    global _STARTED, _MISSING_PACKAGE
    with _LOCK:
        _BOOK.clear()
        _WANTED.clear()
        _STARTED = False
        _MISSING_PACKAGE = False
    from app.modules.progress.history import clear_live_minutes

    clear_live_minutes()


def remember_tick(message: dict, moment: datetime) -> None:
    """Store one full-mode update. Messages without a positive last price are ignored."""
    symbol = message.get("symbol")
    if not isinstance(symbol, str) or not symbol.startswith("NSE:"):
        return
    if message.get("type") not in {None, "sf"}:
        return
    price = _decimal(message.get("ltp"))
    if price is None or price <= 0:
        return
    anchor = quote_anchor(symbol)
    if anchor is None or not _within_band(price, anchor):
        return
    previous = _decimal(message.get("prev_close_price"))
    change = None
    if previous is not None and previous > 0 and _within_band(previous, anchor):
        change = ((price - previous) / previous * Decimal(100)).quantize(Decimal("0.01"))
    with _LOCK:
        _BOOK[symbol] = (moment, QuotePrint(price, change))
    from app.modules.progress.history import note_print

    note_print(symbol, price, moment)


def fresh_ticks(
    codes: set[str] | dict[str, object],
    moment: datetime,
) -> dict[str, QuotePrint]:
    found: dict[str, QuotePrint] = {}
    with _LOCK:
        for code in codes:
            cached = _BOOK.get(code)
            if cached is not None and moment - cached[0] <= _FRESH and cached[1].price > 0:
                found[code] = cached[1]
    return found


def watch_symbols(codes: list[str]) -> None:
    """Remember the actionable symbols and start the socket when this process may."""
    with _LOCK:
        _WANTED.clear()
        _WANTED.update(codes[:_SYMBOL_CAP])
    _ensure_started()


def _within_band(price: Decimal, anchor: Decimal | None) -> bool:
    """A mixed socket update can carry another symbol's price. The quote decides."""
    if anchor is None or anchor <= 0:
        return True
    return abs(price - anchor) / anchor <= _TICK_BAND


def _decimal(raw: object) -> Decimal | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return Decimal(str(raw))
    except Exception:
        return None


def _ensure_started() -> None:
    global _STARTED
    from app.core.config import get_settings

    if get_settings().environment == "test":
        return
    with _LOCK:
        if _STARTED or _MISSING_PACKAGE:
            return
        _STARTED = True
    threading.Thread(target=_supervise, name="fyers-data-socket", daemon=True).start()


def _supervise() -> None:
    global _MISSING_PACKAGE
    while True:
        try:
            _run_socket()
        except ImportError:
            with _LOCK:
                _MISSING_PACKAGE = True
                _STARTED = False
            logger.warning(
                "Fyers data socket package is not installed. Last traded price uses the quote call."
            )
            return
        except Exception:
            logger.warning("Fyers data socket stopped. The quote call remains the fallback.")
        threading.Event().wait(15)


def _socket_log_dir() -> str:
    """The vendor client always opens a log file. Keep it with the other process logs."""
    directory = Path(__file__).resolve().parents[4] / ".quantivo" / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory) + os.sep


def _wanted() -> list[str]:
    with _LOCK:
        return sorted(_WANTED)


def _run_socket() -> None:
    from fyers_apiv3.FyersWebsocket import data_ws

    from app.core.config import get_settings
    from app.core.database import utcnow
    from app.modules.quotes.session import ensure_access_token

    ensure_access_token()
    settings = get_settings()
    app_id = settings.fyers_app_id.strip()
    token = settings.fyers_access_token.strip()
    if not app_id or not token:
        threading.Event().wait(30)
        return
    holder: dict[str, object] = {}

    def on_message(message):
        if isinstance(message, dict):
            remember_tick(message, utcnow())

    def on_connect():
        _subscribe(holder.get("socket"), _wanted())

    def on_error(_message):
        logger.warning("Fyers data socket reported an error")

    def on_close(_message):
        logger.info("Fyers data socket closed")

    socket = data_ws.FyersDataSocket(
        access_token=f"{app_id}:{token}",
        log_path=_socket_log_dir(),
        litemode=False,
        write_to_file=False,
        reconnect=True,
        on_connect=on_connect,
        on_close=on_close,
        on_error=on_error,
        on_message=on_message,
        reconnect_retry=10,
    )
    holder["socket"] = socket
    threading.Thread(
        target=_follow,
        args=(holder, token),
        name="fyers-data-subscribe",
        daemon=True,
    ).start()
    socket.connect()


def _follow(holder: dict[str, object], token: str) -> None:
    """Resubscribe when the call list changes, and stop when the access token changes."""
    seen = set(_wanted())
    _subscribe(holder.get("socket"), sorted(seen))
    while True:
        threading.Event().wait(5)
        if settings_token() != token:
            _close(holder.get("socket"))
            return
        wanted = set(_wanted())
        if wanted == seen:
            continue
        socket = holder.get("socket")
        if seen:
            _unsubscribe(socket, sorted(seen))
        _subscribe(socket, sorted(wanted))
        seen = wanted


def settings_token() -> str:
    from app.core.config import get_settings

    return get_settings().fyers_access_token.strip()


def _subscribe(socket: object, symbols: list[str]) -> None:
    if socket is None or not symbols:
        return
    subscribe = getattr(socket, "subscribe", None)
    if subscribe is None:
        return
    subscribe(symbols=symbols, data_type="SymbolUpdate")


def _unsubscribe(socket: object, symbols: list[str]) -> None:
    if socket is None or not symbols:
        return
    unsubscribe = getattr(socket, "unsubscribe", None)
    if unsubscribe is None:
        return
    unsubscribe(symbols=symbols, data_type="SymbolUpdate")


def _close(socket: object) -> None:
    if socket is None:
        return
    for name in ("close_connection", "disconnect", "close"):
        method = getattr(socket, name, None)
        if method is not None:
            method()
            return
