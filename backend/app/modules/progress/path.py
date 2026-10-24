"""Turn one-minute bars into the call mark. A stored status word is not an input."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.modules.signals.status import entry_deadline

_BAR = timedelta(minutes=1)


@dataclass(frozen=True)
class Progress:
    code: str
    at: datetime | None = None
    level: str | None = None


def assess_path(
    *,
    side: str,
    trigger: Decimal,
    stop: Decimal,
    targets: list[Decimal],
    published_at: datetime,
    bars: list[tuple[datetime, Decimal, Decimal, Decimal]],
    now: datetime,
    covered: bool,
) -> Progress | None:
    """The mark, or None when the window has ended and its minutes are not covered."""

    if trigger <= 0 or not targets:
        return None
    sent = _ist(published_at)
    deadline = entry_deadline(sent)
    moment = _ist(now)
    ordered = sorted(bars, key=lambda bar: _ist(bar[0]))
    entry_at, entry_open = _entry(side, trigger, sent, deadline, ordered)
    if entry_at is None:
        if moment < deadline:
            for opened, high, low, _close in _quads(ordered):
                opened = _ist(opened)
                if opened + _BAR <= sent or opened >= deadline:
                    continue
                if _hit_stop(side, high, low, stop):
                    return Progress("caution", opened)
            return Progress("waiting", None)
        if deadline <= sent or covered:
            return Progress("not_valid", None)
        return None
    mark = "entry"
    at = entry_at
    level = None
    for opened, high, low, _close in _quads(ordered):
        opened = _ist(opened)
        if entry_open is None or opened <= entry_open:
            continue
        hit_stop = _hit_stop(side, high, low, stop)
        hit = [index for index, price in enumerate(targets) if _hit_target(side, high, low, price)]
        if hit_stop and hit:
            continue
        if hit_stop:
            return Progress("stop", opened)
        if not hit:
            continue
        furthest = max(hit)
        if furthest == len(targets) - 1:
            return Progress("final", opened)
        mark = "t1_trail" if furthest == 0 else "t2_trail" if furthest == 1 else "trail"
        at = opened
        level = f"T{furthest + 1}"
    return Progress(mark, at, level)


def _quads(ordered):
    for bar in ordered:
        yield bar[0], bar[1], bar[2], bar[3]


def _entry(side, trigger, sent, deadline, ordered):
    for opened, _high, _low, close in _quads(ordered):
        opened = _ist(opened)
        closed_at = opened + _BAR
        if closed_at <= sent or closed_at > deadline:
            continue
        if _closed_through(side, close, trigger):
            return closed_at, opened
    return None, None


def _closed_through(side: str, close: Decimal, trigger: Decimal) -> bool:
    if side == "SELL":
        return close < trigger
    return close > trigger


def _hit_stop(side: str, high: Decimal, low: Decimal, stop: Decimal) -> bool:
    if side == "SELL":
        return high >= stop
    return low <= stop


def _hit_target(side: str, high: Decimal, low: Decimal, target: Decimal) -> bool:
    if side == "SELL":
        return low <= target
    return high >= target


def _ist(value: datetime) -> datetime:
    from app.modules.signals.status import _as_ist

    return _as_ist(value)
