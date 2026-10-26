"""Equity channel posts. A call needs a buy level, a stop, and at least one target.

The horizon line is kept as published. Recognizing a line does not rewrite it.
A missing stop or target can be read from the following message by the worker.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

_BUY = re.compile(
    r"^(?:buy\.?\s+)?"
    r"([A-Za-z0-9][A-Za-z0-9&.+\- ]{0,40}?)\s+"
    r"(?:@\s*cmp\s+at|cmp\s+at|at\s*cmp|above|@)\s*"
    r"(\d+(?:\.\d+)?)(?:\s+.*)?$",
    re.IGNORECASE,
)
_STOP = re.compile(
    r"^(?:sl|stop\s*loss)\s*(?:at\s+)?(\d+(?:\.\d+)?)(?:\s+.*)?$",
    re.IGNORECASE,
)
_TARGET = re.compile(r"^(?:targets?|taregt|targert|targer)\s*(.+)$", re.IGNORECASE)
_NUMBER = re.compile(r"\d+(?:\.\d+)?\+?(?!\d)(?!\s*%)")
_SPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^a-z0-9 ]+")


@dataclass(frozen=True)
class ParsedEquityCall:
    horizon_raw: str
    name_raw: str
    buy_above: Decimal
    stop_loss: Decimal
    targets: tuple[Decimal, ...]


@dataclass(frozen=True)
class _Draft:
    horizon_raw: str
    explicit_horizon: bool
    name_raw: str | None
    buy_above: Decimal | None
    stop_loss: Decimal | None
    targets: tuple[Decimal, ...]


def parse_equity_call(text: str) -> ParsedEquityCall | None:
    draft = _read_draft(text)
    missing = (
        draft.buy_above is None
        or draft.stop_loss is None
        or not draft.targets
        or not draft.name_raw
    )
    if missing:
        return None
    return ParsedEquityCall(
        horizon_raw=draft.horizon_raw.strip() or "Unlisted",
        name_raw=draft.name_raw,
        buy_above=draft.buy_above,
        stop_loss=realistic_stop(draft.buy_above, draft.stop_loss),
        targets=tuple(
            align_prices("BUY", draft.buy_above, draft.stop_loss, list(draft.targets))[2]
        ),
    )


def continue_equity_call(opening: str, follow_up: str) -> ParsedEquityCall | None:
    """Use the next message when the opening already names the buy and is short a stop or target.

    The follow-up is not used when it is already a complete call, names another stock,
    or carries a different horizon line.
    """

    if parse_equity_call(opening) is not None or parse_equity_call(follow_up) is not None:
        return None
    first = _read_draft(opening)
    if first.buy_above is None or not first.name_raw:
        return None
    second = _read_draft(follow_up)
    if second.name_raw and not _same_name(second.name_raw, first.name_raw):
        return None
    if second.explicit_horizon and first.horizon_raw:
        if _key(second.horizon_raw) != _key(first.horizon_raw):
            return None
    return parse_equity_call(f"{opening.rstrip()}\n{follow_up.lstrip()}")


def _read_draft(text: str) -> _Draft:
    lines = [_clean_line(line) for line in (text or "").splitlines()]
    lines = [line for line in lines if line]
    horizon_raw = ""
    explicit_horizon = False
    buy: re.Match[str] | None = None
    stop: re.Match[str] | None = None
    target: re.Match[str] | None = None
    for index, line in enumerate(lines):
        buy_match = _BUY.match(line)
        stop_match = _STOP.match(line)
        target_match = _TARGET.match(line)
        if buy_match:
            buy = buy_match
            continue
        if stop_match:
            stop = stop_match
            continue
        if target_match:
            target = target_match
            continue
        if _looks_like_horizon(line):
            horizon_raw = line
            explicit_horizon = True
            continue
        if index == 0 and not horizon_raw:
            horizon_raw = line

    name = None if buy is None else buy.group(1).strip(" .")
    if not name or len(name.split()) > 4:
        name = None
        buy = None
    targets = () if target is None else _parse_targets(target.group(1))
    return _Draft(
        horizon_raw=horizon_raw,
        explicit_horizon=explicit_horizon,
        name_raw=name,
        buy_above=None if buy is None else Decimal(buy.group(2)),
        stop_loss=None if stop is None else Decimal(stop.group(1)),
        targets=targets,
    )


def _same_name(left: str, right: str) -> bool:
    return " ".join(left.split()).casefold() == " ".join(right.split()).casefold()


def realistic_stop(buy_above: Decimal, stop: Decimal) -> Decimal:
    """Drop a trailing zero when a stop was typed one digit too long.

    650 written as 6500 is the usual slip. A stop only a little above the buy,
    such as 1030 against 1005, is left as written.
    """

    return _shift_to(stop, buy_above, buy_above, "below")


def align_prices(
    side: str,
    trigger: Decimal,
    stop: Decimal,
    targets: list[Decimal],
    anchor: Decimal | None = None,
) -> tuple[Decimal, Decimal, list[Decimal]]:
    """Shift a wrong-side stop or target by a power of ten.

    The current price is the check. When it is missing, the buy is the check.
    A level already on the right side of the buy is kept. The buy itself is kept.
    """

    scale = anchor if anchor is not None and anchor > 0 else trigger
    stop_place = "above" if side == "SELL" else "below"
    target_place = "below" if side == "SELL" else "above"
    return (
        trigger,
        _shift_to(stop, trigger, scale, stop_place),
        [_shift_to(price, trigger, scale, target_place) for price in targets],
    )


_NEAR = Decimal(8)


def _shift_to(raw: Decimal, pivot: Decimal, scale: Decimal, place: str) -> Decimal:
    if raw <= 0 or pivot <= 0 or scale <= 0:
        return raw
    if _acceptable(raw, pivot, scale, place):
        return raw
    best: Decimal | None = None
    best_gap: Decimal | None = None
    for power in range(-4, 5):
        if power == 0:
            continue
        candidate = raw * (Decimal(10) ** power)
        if not _acceptable(candidate, pivot, scale, place):
            continue
        gap = abs((candidate / scale).ln())
        if best_gap is None or gap < best_gap:
            best = candidate
            best_gap = gap
    return raw if best is None else best


def _acceptable(candidate: Decimal, pivot: Decimal, scale: Decimal, place: str) -> bool:
    if candidate <= 0 or not _near(candidate, scale):
        return False
    if place == "above":
        return candidate > pivot
    if place == "below":
        return candidate < pivot
    return True


def _near(left: Decimal, right: Decimal) -> bool:
    if left <= 0 or right <= 0:
        return False
    return left / right <= _NEAR and right / left <= _NEAR


def session_horizon(horizon_raw: str) -> bool:
    """True only for a same-day horizon line, not for 'Intraday to 7 days'."""

    key = _key(horizon_raw)
    if "intraday to" in key:
        return False
    return key in {"intraday", "intarday", "intrday", "btst"} or key.startswith("btst ")


def seven_day_horizon(horizon_raw: str) -> bool:
    """The Equity line 'Intraday to 7 days', including the published typos."""

    key = _key(horizon_raw)
    return "intraday to 7" in key or "intarday to 7" in key or "intrday to 7" in key


def _looks_like_horizon(raw: str) -> bool:
    key = _key(raw)
    if not key:
        return False
    if key.startswith(("long", "short", "medium", "mid ", "positional", "btst")):
        return True
    return "intraday" in key or "intarday" in key or "intrday" in key


def _key(raw: str) -> str:
    key = raw.strip().lower().replace("-", " ").replace("/", " ")
    key = _NON_WORD.sub(" ", key)
    return _SPACE.sub(" ", key).strip()


def _parse_targets(blob: str) -> tuple[Decimal, ...]:
    parsed: list[Decimal] = []
    for token in _NUMBER.findall(blob):
        parsed.append(Decimal(token.rstrip("+")))
    if len(parsed) > 3:
        parsed = [parsed[0], parsed[1], parsed[-1]]
    return tuple(parsed)


def _clean_line(line: str) -> str:
    return _SPACE.sub(" ", line.replace("\u00a0", " ")).strip()
