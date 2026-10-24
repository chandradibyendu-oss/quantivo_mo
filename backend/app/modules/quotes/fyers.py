"""Fyers last traded prices for NSE cash symbols.

The app id and access token stay in the environment. They are not written to a
table, a log, or an audit payload. A missing token or a failed read leaves the
price empty. The call list still returns.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.core.config import get_settings
from app.core.database import utcnow
from app.modules.feeds.equity_directory import cached_series

logger = logging.getLogger("quantivo.quotes")

FYERS_QUOTES_URL = "https://api-t1.fyers.in/data/quotes"
_CHUNK = 50
_TIMEOUT_SECONDS = 4
_TTL = timedelta(seconds=60)
_SYMBOL = re.compile(r"^[A-Z0-9&-]+$")
_LOCK = threading.Lock()
_SERIES: dict[str, str] | None = None
_CACHE: dict[str, tuple[datetime, QuotePrint | None]] = {}
_PAUSED_UNTIL: datetime | None = None
_PAUSE = timedelta(minutes=15)


class QuoteRateLimit(Exception):
    """Fyers or its edge refused the read. The next try waits."""

QuoteSource = Literal["fyers", "unconfigured", "unavailable"]


def clear_quote_cache() -> None:
    global _PAUSED_UNTIL
    with _LOCK:
        _CACHE.clear()
        _PAUSED_UNTIL = None


def quotes_paused(moment: datetime) -> bool:
    with _LOCK:
        return _PAUSED_UNTIL is not None and moment < _PAUSED_UNTIL


def pause_quotes(moment: datetime) -> None:
    global _PAUSED_UNTIL
    with _LOCK:
        _PAUSED_UNTIL = moment + _PAUSE


@dataclass(frozen=True)
class QuotePrint:
    price: Decimal
    change_percent: Decimal | None = None


@dataclass(frozen=True)
class QuoteBatch:
    source: QuoteSource
    prices: dict[tuple[str, str], Decimal]
    changes: dict[tuple[str, str], Decimal] = field(default_factory=dict)


def access_rejected(body: str) -> bool:
    """True when Fyers rejected the access token. The body is not logged."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    return payload.get("code") in {-8, -15, -16, -17}


def read_last_prices(
    pairs: list[tuple[str, str]],
    *,
    app_id: str | None = None,
    access_token: str | None = None,
    opener=None,
    now: datetime | None = None,
    cache: dict[str, tuple[datetime, QuotePrint | None]] | None = None,
    series: dict[str, str] | None = None,
    chunk_size: int = _CHUNK,
) -> QuoteBatch:
    """Map (exchange, symbol) to a last price. Unconfigured and failed reads carry no prices."""
    from_settings = app_id is None and access_token is None
    if from_settings:
        from app.modules.quotes.session import ensure_access_token

        ensure_access_token()
    resolved_id, resolved_token = _credentials(app_id, access_token)
    if not resolved_id or not resolved_token:
        return QuoteBatch("unconfigured", {})

    moment = now or utcnow()
    store = _CACHE if cache is None else cache
    wanted: dict[str, tuple[str, str]] = {}
    for exchange, symbol in pairs:
        code = fyers_code(exchange, symbol, series)
        if code is not None:
            wanted.setdefault(code, (exchange, symbol))
    if not wanted:
        return QuoteBatch("fyers", {})

    fresh, missing = _split_cache(wanted, store, moment)
    if missing and quotes_paused(moment):
        return QuoteBatch("unavailable", {})
    if missing:
        fetched = _fetch(
            missing,
            resolved_id,
            resolved_token,
            opener,
            chunk_size,
            allow_refresh=from_settings,
            now=moment,
        )
        if fetched is None:
            return QuoteBatch("unavailable", {})
        with _LOCK:
            for code in missing:
                store[code] = (moment, fetched.get(code))
            fresh = {code: store[code][1] for code in wanted if code in store}

    prices: dict[tuple[str, str], Decimal] = {}
    changes: dict[tuple[str, str], Decimal] = {}
    for code, pair in wanted.items():
        printed = fresh.get(code)
        if printed is None:
            continue
        prices[pair] = printed.price
        if printed.change_percent is not None:
            changes[pair] = printed.change_percent
    return QuoteBatch("fyers", prices, changes)


def fyers_code(exchange: str, symbol: str, series: dict[str, str] | None = None) -> str | None:
    """Fyers cash code, such as NSE:SBIN-EQ. Other exchanges and multi-word names are omitted."""
    if exchange.strip().upper() != "NSE":
        return None
    ticker = symbol.strip().upper()
    if not _SYMBOL.fullmatch(ticker):
        return None
    chosen = _series_for(ticker, series)
    return f"NSE:{ticker}-{chosen}"


def parse_fyers_quotes(body: str) -> dict[str, QuotePrint] | None:
    """Symbol code to last price and the percent from the previous close."""
    try:
        payload = json.loads(body, parse_float=Decimal)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    rows = payload.get("d")
    if payload.get("s") != "ok" or not isinstance(rows, list):
        return None
    found: dict[str, QuotePrint] = {}
    for item in rows:
        if not isinstance(item, dict) or item.get("s") != "ok":
            continue
        name = item.get("n")
        values = item.get("v")
        raw = values.get("lp") if isinstance(values, dict) else None
        price = _decimal(raw)
        if not isinstance(name, str) or price is None or price <= 0:
            continue
        found[name] = QuotePrint(price, _change_percent(values, price))
    return found


def _decimal(raw: object) -> Decimal | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return None


def _change_percent(values: dict, price: Decimal) -> Decimal | None:
    """Percent versus the previous close. Fyers sends it as chp."""
    quoted = _decimal(values.get("chp"))
    if quoted is not None:
        return quoted.quantize(Decimal("0.01"))
    previous = _decimal(values.get("prev_close_price"))
    if previous is None or previous <= 0:
        return None
    return ((price - previous) / previous * Decimal(100)).quantize(Decimal("0.01"))


def _credentials(app_id: str | None, access_token: str | None) -> tuple[str, str]:
    if app_id is None or access_token is None:
        settings = get_settings()
        if app_id is None:
            app_id = settings.fyers_app_id
        if access_token is None:
            access_token = settings.fyers_access_token
    return app_id.strip(), access_token.strip()


def _series_for(ticker: str, series: dict[str, str] | None) -> str:
    if series is not None:
        return series.get(ticker, "EQ")
    return _loaded_series().get(ticker, "EQ")


def _loaded_series() -> dict[str, str]:
    global _SERIES
    if _SERIES is None:
        _SERIES = cached_series()
    return _SERIES


def _split_cache(
    wanted: dict[str, tuple[str, str]],
    store: dict[str, tuple[datetime, QuotePrint | None]],
    moment: datetime,
) -> tuple[dict[str, QuotePrint | None], list[str]]:
    fresh: dict[str, QuotePrint | None] = {}
    missing: list[str] = []
    with _LOCK:
        for code in wanted:
            cached = store.get(code)
            if cached is not None and moment - cached[0] < _TTL:
                fresh[code] = cached[1]
            else:
                missing.append(code)
    return fresh, missing


def _fetch(
    codes: list[str],
    app_id: str,
    access_token: str,
    opener,
    chunk_size: int,
    *,
    allow_refresh: bool,
    now: datetime,
) -> dict[str, QuotePrint] | None:
    send = opener or _open
    found: dict[str, QuotePrint] = {}
    size = max(1, chunk_size)
    for start in range(0, len(codes), size):
        chunk = codes[start : start + size]
        encoded = ",".join(urllib.parse.quote(code, safe=":") for code in chunk)
        try:
            body = send(f"{FYERS_QUOTES_URL}?symbols={encoded}", f"{app_id}:{access_token}")
        except QuoteRateLimit:
            pause_quotes(now)
            logger.warning("Fyers quotes are paused for 15 minutes after a rate limit")
            return None
        except (OSError, ValueError):
            logger.warning("Fyers quotes could not be read")
            return None
        parsed = parse_fyers_quotes(body)
        if parsed is None and allow_refresh and access_rejected(body):
            from app.modules.quotes.session import ensure_access_token

            if ensure_access_token(force=True):
                settings = get_settings()
                return _fetch(
                    codes,
                    settings.fyers_app_id,
                    settings.fyers_access_token,
                    opener,
                    chunk_size,
                    allow_refresh=False,
                    now=now,
                )
        if parsed is None:
            logger.warning("Fyers quotes could not be read")
            return None
        found.update(parsed)
    return found


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
        if exc.code == 429:
            raise QuoteRateLimit from None
        raise
