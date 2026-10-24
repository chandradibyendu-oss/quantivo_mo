"""Session candles for the chart. A last traded price is not a candle."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.core.config import get_settings
from app.modules.feeds.window import IST, session_day
from app.modules.progress.history import day_state, request_day
from app.modules.quotes.fyers import fyers_code

_OPEN = 9 * 60 + 15
_CLOSE = 15 * 60 + 30


def session_candles(
    *,
    exchange: str,
    symbol: str,
    segment: str,
    interval: str,
    now: datetime,
) -> tuple[str, list[dict[str, str]]]:
    """The session's bars, and a state: ready, checking, unconfigured, or unavailable."""

    if segment.casefold() != "equity":
        return "unavailable", []
    code = fyers_code(exchange, symbol)
    if code is None:
        return "unavailable", []
    if not get_settings().fyers_quotes_configured:
        return "unconfigured", []
    day = session_day(now)
    state, bars = day_state(code, day, now.astimezone(IST))
    if state in {"missing", "stale"}:
        request_day(code, day, budget=[1])
        if state == "missing":
            return "checking", []
    if state == "failed" or not bars:
        return "unavailable" if state == "failed" else "checking", []
    chosen = _session_bars(bars)
    if interval == "5m":
        chosen = _fold_five(chosen)
    return "ready", [_candle(bar) for bar in chosen]


def _session_bars(bars):
    kept = []
    for bar in sorted(bars, key=lambda item: item[0]):
        opened = bar[0].astimezone(IST)
        minute = opened.hour * 60 + opened.minute
        if _OPEN <= minute <= _CLOSE:
            kept.append(bar)
    return kept


def _fold_five(bars):
    groups: dict[datetime, list] = {}
    for bar in bars:
        opened = bar[0].astimezone(IST).replace(second=0, microsecond=0)
        minute = opened.hour * 60 + opened.minute
        slot = _OPEN + ((minute - _OPEN) // 5) * 5
        bucket = opened.replace(hour=slot // 60, minute=slot % 60)
        groups.setdefault(bucket, []).append(bar)
    folded = []
    for bucket in sorted(groups):
        chunk = groups[bucket]
        first = chunk[0]
        opened_price = first[4] if len(first) > 4 else first[3]
        folded.append(
            (
                bucket,
                max(item[1] for item in chunk),
                min(item[2] for item in chunk),
                chunk[-1][3],
                opened_price,
            )
        )
    return folded


def _candle(bar) -> dict[str, str]:
    opened = bar[0].astimezone(IST)
    open_price = bar[4] if len(bar) > 4 else bar[3]
    return {
        "time": opened.strftime("%H:%M"),
        "open": format(Decimal(open_price), "f"),
        "high": format(Decimal(bar[1]), "f"),
        "low": format(Decimal(bar[2]), "f"),
        "close": format(Decimal(bar[3]), "f"),
    }
