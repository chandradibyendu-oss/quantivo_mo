"""Equity channel posts. A call needs a buy level, a stop, and at least one target.

The horizon line is kept as published. Recognizing a line does not rewrite it.
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


def parse_equity_call(text: str) -> ParsedEquityCall | None:
    lines = [_clean_line(line) for line in (text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return None

    horizon_raw = ""
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
            continue
        if index == 0 and not horizon_raw:
            horizon_raw = line

    if buy is None or stop is None or target is None:
        return None
    targets = _parse_targets(target.group(1))
    if not targets:
        return None
    name = buy.group(1).strip(" .")
    if not name or len(name.split()) > 4:
        return None
    return ParsedEquityCall(
        horizon_raw=horizon_raw.strip() or "Unlisted",
        name_raw=name,
        buy_above=Decimal(buy.group(2)),
        stop_loss=realistic_stop(Decimal(buy.group(2)), Decimal(stop.group(1))),
        targets=targets,
    )


def realistic_stop(buy_above: Decimal, stop: Decimal) -> Decimal:
    """Drop a trailing zero when a stop was typed one digit too long.

    650 written as 6500 is the usual slip. A stop only a little above the buy,
    such as 1030 against 1005, is left as written.
    """

    if buy_above <= 0 or stop <= buy_above:
        return stop
    floor = buy_above / Decimal(2)
    candidate = stop
    while candidate > buy_above and candidate % Decimal(10) == 0:
        nxt = candidate / Decimal(10)
        if nxt <= 0 or nxt < floor:
            break
        candidate = nxt
    if candidate < buy_above:
        return candidate
    return stop


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
