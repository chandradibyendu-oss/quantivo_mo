"""Turn one Equity post into the platform signal shape."""

import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.feeds.equity_directory import (
    EquityDirectory,
    alias_symbol,
    get_equity_directory,
)
from app.modules.feeds.equity_parser import ParsedEquityCall, session_horizon, seven_day_horizon
from app.modules.scanners.models import SourceChannel
from app.modules.signals.models import Signal
from app.modules.signals.normalization import NormalizedSignal

_SYMBOL = re.compile(r"^[A-Z][A-Z0-9&.\-]{0,31}$")
_UNMATCHED_NOTE = "The posted name did not match one NSE symbol."
_AMBIGUOUS_NOTE = "The posted name matches more than one NSE symbol."


def to_signal(
    parsed: ParsedEquityCall,
    *,
    channel: SourceChannel,
    external_ref: str,
    published_at: datetime,
) -> NormalizedSignal:
    symbol, match_status, note = _symbol_match(parsed.name_raw)
    intraday = session_horizon(parsed.horizon_raw)
    targets = tuple((f"T{index}", price) for index, price in enumerate(parsed.targets, start=1))
    expires_at = _expires_at(parsed.horizon_raw, published_at)
    if intraday:
        timeframe = "INTRADAY"
        product_hint = "MIS"
    else:
        timeframe = "POSITIONAL"
        product_hint = "CNC"
    return NormalizedSignal(
        external_ref=external_ref,
        symbol=symbol,
        exchange="NSE",
        side="BUY",
        timeframe=timeframe,
        product_hint=product_hint,
        trigger_price=parsed.buy_above,
        stop_loss=parsed.stop_loss,
        targets=targets,
        provider_note=note,
        status="active",
        published_at=published_at,
        expires_at=expires_at,
        segment=channel.segment,
        channel_code=channel.code,
        horizon_raw=parsed.horizon_raw[:80],
        lot_size=1,
        match_status=match_status,
        origin="channel",
    )


def _expires_at(horizon_raw: str, published_at: datetime) -> datetime:
    if session_horizon(horizon_raw):
        return published_at + timedelta(hours=8)
    if seven_day_horizon(horizon_raw):
        return published_at + timedelta(days=7)
    return published_at + timedelta(days=30)


def match_posted_name(
    name_raw: str,
    directory: EquityDirectory | None,
) -> tuple[str, str, str | None]:
    """Resolve a posted name to one NSE symbol. Ambiguous and unknown names stay as written."""

    alias = alias_symbol(name_raw)
    if directory is not None:
        found = directory.lookup(name_raw)
        if found.status == "matched" and found.symbol:
            return found.symbol[:32], "matched", None
        if found.status == "ambiguous":
            return _stored_name(name_raw), "ambiguous", _AMBIGUOUS_NOTE
        if alias:
            return alias[:32], "matched", None
        return _stored_name(name_raw), "unmatched", _UNMATCHED_NOTE
    if alias:
        return alias[:32], "matched", None
    return _token_rule(name_raw)


def rematch_channel_names(db: Session) -> int:
    """Apply the NSE list to stored channel calls. A desk note stays. The hash stays."""

    directory = get_equity_directory()
    if directory is None:
        return 0
    changed = 0
    for signal in db.scalars(select(Signal).where(Signal.origin == "channel")).all():
        symbol, status, note = match_posted_name(signal.symbol, directory)
        if symbol == signal.symbol and status == signal.match_status:
            continue
        signal.symbol = symbol
        signal.match_status = status
        if note is not None or signal.provider_note in (None, _UNMATCHED_NOTE, _AMBIGUOUS_NOTE):
            signal.provider_note = note
        changed += 1
    return changed


def _symbol_match(name_raw: str) -> tuple[str, str, str | None]:
    return match_posted_name(name_raw, get_equity_directory())


def _token_rule(name_raw: str) -> tuple[str, str, str | None]:
    token = _stored_name(name_raw)
    if " " not in token and _SYMBOL.fullmatch(token):
        return token, "matched", None
    return token, "unmatched", _UNMATCHED_NOTE


def _stored_name(name_raw: str) -> str:
    token = " ".join(name_raw.split()).upper()
    return token[:32] or "UNKNOWN"


def external_ref_for(channel_id: str, message_id: int) -> str:
    ref = f"{channel_id}:{message_id}"
    if len(ref) > 128 or message_id < 1:
        raise ValueError("message identity is not usable")
    return ref
