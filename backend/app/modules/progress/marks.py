"""Put the price mark and its minute on a call. Quantity is not an input."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.core.config import get_settings
from app.modules.progress.history import IST, day_state, request_day
from app.modules.progress.path import Progress, assess_path
from app.modules.quotes.fyers import fyers_code
from app.modules.signals.schemas import SignalCard
from app.modules.signals.status import entry_deadline

CLOSED_MARKS = frozenset({"not_valid", "final", "stop"})

_WORDS = {
    "waiting": "Waiting",
    "caution": "Caution",
    "not_valid": "Not valid",
    "entry": "Entry",
    "t1_trail": "T1 trail",
    "t2_trail": "T2 trail",
    "final": "Final",
    "stop": "Stop",
    "checking": "Checking",
}
_HINTS = {
    "waiting": "The window is open. No one-minute candle has closed through the trigger.",
    "caution": (
        "The stop was touched in this minute. The window is still open, and there is no entry yet."
    ),
    "not_valid": (
        "The window ended. No one-minute candle closed through the trigger, so there is no entry."
    ),
    "entry": "The one-minute candle closed through the trigger at this time. That is the entry.",
    "t1_trail": (
        "T1 was touched in this minute. A later target remains. The published stop is unchanged."
    ),
    "t2_trail": (
        "T2 was touched in this minute. A later target remains. The published stop is unchanged."
    ),
    "trail": (
        "This target was touched in this minute. A later target remains. "
        "The published stop is unchanged."
    ),
    "final": "The last target was touched in this minute. That is the exit.",
    "stop": "The stop was touched in this minute after entry. That is the exit.",
    "checking": (
        "Reading the one-minute bars. "
        "The entry or exit time appears with the minute that produced it."
    ),
}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def apply_progress(cards: list[SignalCard], *, now: datetime) -> list[SignalCard]:
    budget = [8]
    return [_paint(card, now, budget) for card in cards]


def terminal_mark(
    *,
    exchange: str,
    symbol: str,
    segment: str,
    side: str,
    trigger: Decimal,
    stop: Decimal,
    targets: list[Decimal],
    published_at: datetime,
    now: datetime,
) -> str | None:
    """A finished price mark already read from bars. This does not start a new read."""

    progress = _resolve(
        exchange=exchange,
        symbol=symbol,
        segment=segment,
        side=side,
        trigger=trigger,
        stop=stop,
        targets=targets,
        published_at=published_at,
        now=now,
        budget=[0],
        enqueue=False,
    )
    if progress is None or progress.code not in CLOSED_MARKS:
        return None
    return progress.code


def _paint(card: SignalCard, now: datetime, budget: list[int]) -> SignalCard:
    if card.status != "active" or card.guide == "no_symbol" or card.segment.casefold() != "equity":
        return card
    try:
        trigger = Decimal(card.provider_values.trigger_price)
        stop = Decimal(card.provider_values.stop_loss)
        targets = [Decimal(item.price) for item in card.provider_values.targets]
    except InvalidOperation:
        return card
    progress = _resolve(
        exchange=card.exchange,
        symbol=card.symbol,
        segment=card.segment,
        side=card.side,
        trigger=trigger,
        stop=stop,
        targets=targets,
        published_at=card.published_at,
        now=now,
        budget=budget,
        enqueue=True,
    )
    if progress is None:
        return card
    if progress.code == "pending":
        return card.model_copy(
            update={
                "guide": "checking",
                "guide_label": _WORDS["checking"],
                "guide_hint": _HINTS["checking"],
            }
        )
    if progress.code == "unread":
        return card.model_copy(
            update={
                "guide_hint": (
                    f"{card.guide_hint} The one-minute bars for the entry and exit time "
                    "could not be read."
                )
            }
        )
    word = _WORDS.get(progress.code) or (
        f"{progress.level} trail" if progress.level else "Trail"
    )
    label = word if progress.at is None else f"{word} {_clock(progress.at, now)}"
    return card.model_copy(
        update={
            "guide": progress.code if progress.code in _WORDS else "trail",
            "guide_label": label,
            "guide_hint": _HINTS.get(progress.code, _HINTS["trail"]),
            "executable": card.executable and progress.code not in CLOSED_MARKS,
        }
    )


def _resolve(
    *,
    exchange: str,
    symbol: str,
    segment: str,
    side: str,
    trigger: Decimal,
    stop: Decimal,
    targets: list[Decimal],
    published_at: datetime,
    now: datetime,
    budget: list[int],
    enqueue: bool,
) -> Progress | None:
    if segment.casefold() != "equity" or trigger <= 0 or not targets:
        return None
    code = fyers_code(exchange, symbol)
    if code is None:
        return None
    sent = published_at.astimezone(IST)
    deadline = entry_deadline(sent)
    moment = now.astimezone(IST)
    if not get_settings().fyers_quotes_configured:
        return None
    window_days = _session_days(sent.date(), deadline.date())
    if not window_days:
        return None
    bars, pending, failed = _load(code, window_days, moment, budget, enqueue)
    if pending:
        return Progress("pending", None)
    if failed or not _window_covered(bars, sent, deadline, moment):
        return Progress("unread", None) if failed else None
    progress = assess_path(
        side=side,
        trigger=trigger,
        stop=stop,
        targets=targets,
        published_at=sent,
        bars=bars,
        now=moment,
        covered=True,
    )
    if progress is None or progress.code in {"waiting", "caution", "not_valid"} | CLOSED_MARKS:
        return progress
    later = _session_days(sent.date(), moment.date())
    extra, later_pending, _later_failed = _load(
        code, later, moment, budget, enqueue, stop_at_gap=True
    )
    if not extra:
        return progress
    refined = assess_path(
        side=side,
        trigger=trigger,
        stop=stop,
        targets=targets,
        published_at=sent,
        bars=bars + extra,
        now=moment,
        covered=True,
    )
    if later_pending:
        return refined
    return refined


def _load(
    code: str,
    days: list[date],
    now: datetime,
    budget: list[int],
    enqueue: bool,
    stop_at_gap: bool = False,
):
    bars: list[tuple[datetime, Decimal, Decimal, Decimal]] = []
    pending = False
    failed = False
    for day in days:
        if day > now.date():
            break
        state, found = day_state(code, day, now)
        if state in {"ready", "stale"}:
            bars.extend(found)
            if state == "stale" and enqueue:
                request_day(code, day, budget=budget)
            continue
        if state == "failed":
            failed = True
            if stop_at_gap:
                break
            continue
        pending = True
        if enqueue:
            request_day(code, day, budget=budget)
        if stop_at_gap:
            break
    return bars, pending, failed


def _window_covered(bars, sent: datetime, deadline: datetime, now: datetime) -> bool:
    if deadline <= sent:
        return True
    if now < deadline:
        return True
    if not bars:
        return deadline.date() < now.date()
    last_close = max(opened.astimezone(IST) for opened, *_rest in bars) + timedelta(minutes=1)
    if deadline.date() < now.date():
        return True
    return last_close >= deadline


def _session_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _clock(moment: datetime, now: datetime) -> str:
    local = moment.astimezone(IST)
    clock = local.strftime("%H:%M")
    if local.date() == now.astimezone(IST).date():
        return clock
    return f"{local.day} {_MONTHS[local.month - 1]} {clock}"
