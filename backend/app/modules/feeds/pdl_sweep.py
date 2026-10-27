"""Turn a PDL Sweep live payload into calls. History is included."""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.feeds.equity_parser import session_horizon
from app.modules.feeds.models import SourceFeed
from app.modules.feeds.normalize import _expires_at
from app.modules.feeds.service import PollReport
from app.modules.scanners.models import SourceChannel
from app.modules.signals.normalization import NormalizedSignal
from app.modules.signals.service import IngestOutcome, ingest

logger = logging.getLogger("quantivo.feeds")

IST = ZoneInfo("Asia/Kolkata")
_MONEY = Decimal("0.0001")
_DEFAULT_HORIZON = "Intraday"
_SIDES = {"LONG": "BUY", "SHORT": "SELL"}
_HIT_LINE = re.compile(r"^target_hit=(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})$", re.MULTILINE)
_STARS_LINE = re.compile(r"^stars=([1-5])$", re.MULTILINE)
_RATE_LINE = re.compile(r"^hit_rate=(\d{1,3})$", re.MULTILINE)
_HISTORY_LINE = re.compile(r"^history=(\d+)/(\d+)$", re.MULTILINE)
_HIDDEN_NOTE = ("target_hit=", "stars=", "hit_rate=", "history=")
_FINAL_HINT = "The last target was touched in this minute. That is the exit."
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def calls_from_payload(payload: object, *, channel: SourceChannel) -> list[NormalizedSignal]:
    """Map `today` and `history`. A missing horizon is Intraday. A sent horizon is kept."""

    if not isinstance(payload, dict):
        return []
    drafts: list[NormalizedSignal] = []
    seen: set[str] = set()
    for key in ("today", "history"):
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            draft = _call(row, channel=channel)
            if draft is None or draft.external_ref in seen:
                continue
            seen.add(draft.external_ref)
            drafts.append(draft)
    return drafts


def poll_http_feeds(
    db: Session,
    fetch,
    *,
    now: datetime,
    last_polled: dict,
) -> PollReport:
    """GET each active HTTP feed when its interval is due. Only a PDL body is stored."""

    feeds = db.scalars(
        select(SourceFeed).where(SourceFeed.kind == "http_api", SourceFeed.status == "active")
    ).all()
    if not feeds:
        return PollReport("unused", 0, 0, 0, 0, 0)
    created = unchanged = revised = skipped = 0
    for feed in feeds:
        options = feed.options or {}
        interval = int(options.get("poll_seconds") or 60)
        previous = last_polled.get(feed.id)
        if previous is not None and (now - previous).total_seconds() < interval:
            continue
        channel = db.get(SourceChannel, feed.source_channel_id)
        if channel is None or channel.status != "active" or channel.segment != "equity":
            skipped += 1
            continue
        url = str(options.get("url") or "")
        headers = _auth_header(options.get("auth_env"))
        if headers is None:
            skipped += 1
            last_polled[feed.id] = now
            continue
        try:
            payload = fetch(url, headers)
        except Exception:
            logger.warning("http feed unread host=%s", _host(url))
            skipped += 1
            continue
        last_polled[feed.id] = now
        if not isinstance(payload, dict) or ("today" not in payload and "history" not in payload):
            logger.info("http feed skipped host=%s reason=not_pdl_sweep", _host(url))
            skipped += 1
            continue
        tally = {"created": 0, "unchanged": 0, "revised": 0, "skipped": 0}
        for draft in calls_from_payload(payload, channel=channel):
            outcome = ingest(
                db,
                scanner_id=channel.scanner_id,
                draft=draft,
                correlation_id="pdl-sweep",
            )
            if outcome is IngestOutcome.CREATED:
                tally["created"] += 1
            elif outcome is IngestOutcome.REVISED:
                tally["revised"] += 1
            else:
                tally["unchanged"] += 1
        created += tally["created"]
        unchanged += tally["unchanged"]
        revised += tally["revised"]
        skipped += tally["skipped"]
    return PollReport("used", len(feeds), created, unchanged, revised, skipped)


def _call(row: object, *, channel: SourceChannel) -> NormalizedSignal | None:
    if not isinstance(row, dict):
        return None
    symbol = str(row.get("symbol") or "").strip().upper()
    if not symbol or len(symbol) > 32 or any(char.isspace() for char in symbol):
        return None
    side = _SIDES.get(str(row.get("signal") or "").strip().upper())
    trigger = _money(row.get("entry"))
    stop = _money(row.get("stop"))
    target = _money(row.get("target"))
    if side is None or trigger is None or stop is None or target is None:
        return None
    trade_day = _day(row.get("trade_date"))
    clock = _hhmm(str(row.get("signal_time") or ""))
    if trade_day is None or clock is None:
        return None
    published = datetime(trade_day.year, trade_day.month, trade_day.day, *clock, tzinfo=IST)
    horizon = _horizon(row)
    intraday = session_horizon(horizon)
    return NormalizedSignal(
        external_ref=(
            f"pdl:{symbol}:{trade_day.isoformat()}:{clock[0]:02d}:{clock[1]:02d}"[:128]
        ),
        symbol=symbol,
        exchange="NSE",
        side=side,
        timeframe="INTRADAY" if intraday else "POSITIONAL",
        product_hint="MIS" if intraday else "CNC",
        trigger_price=trigger,
        stop_loss=stop,
        targets=(("T1", target),),
        provider_note=_note(row),
        status="active",
        published_at=published,
        expires_at=_expires(horizon, published, trade_day),
        segment=channel.segment,
        channel_code=channel.code,
        horizon_raw=horizon,
        lot_size=1,
        match_status="matched",
        origin="channel",
    )


def outcome_guide(
    note: str | None,
    guide: str,
    *,
    now: datetime | None = None,
) -> tuple[str, str, str] | None:
    """A recorded target hit is Final. The desk does not send a stop time."""

    if guide == "no_symbol":
        return None
    found = _HIT_LINE.search(note or "")
    if found is None:
        return None
    clock = found.group(2)
    label = f"Final {clock}"
    if now is not None:
        hit_day = date.fromisoformat(found.group(1))
        today = now.astimezone(IST).date() if now.tzinfo is not None else now.date()
        if hit_day != today:
            label = f"Final {hit_day.day} {_MONTHS[hit_day.month - 1]} {clock}"
    return "final", label, _FINAL_HINT


def desk_stars(note: str | None) -> tuple[int, str] | None:
    """The desk's 1 to 5 mark. None when this row did not send one."""

    found = _STARS_LINE.search(note or "")
    if found is None:
        return None
    parts: list[str] = []
    history = _HISTORY_LINE.search(note or "")
    if history is not None:
        parts.append(
            f"{int(history.group(1))} of {int(history.group(2))} "
            "reached the target within 7 days"
        )
    rate = _RATE_LINE.search(note or "")
    if rate is not None:
        parts.append(f"{rate.group(1)}% 7-day target touch rate")
    hint = ". ".join(parts) + "." if parts else "The desk's 7-day target touch rating."
    return int(found.group(1)), hint


def visible_note(note: str | None) -> str | None:
    if not note:
        return None
    lines = [line for line in note.splitlines() if not line.startswith(_HIDDEN_NOTE)]
    cleaned = "\n".join(lines).strip()
    return cleaned or None


def _note(row: dict) -> str | None:
    lines: list[str] = []
    company = str(row.get("company_name") or "").strip()
    if company:
        lines.append(company[:240])
    hit_day = _day(row.get("target_hit_date"))
    hit_clock = _hhmm(str(row.get("target_hit_time") or ""))
    if hit_day is not None and hit_clock is not None:
        lines.append(f"target_hit={hit_day.isoformat()} {hit_clock[0]:02d}:{hit_clock[1]:02d}")
    stars = _stars(row.get("stars"))
    if stars is not None:
        lines.append(f"stars={stars}")
    rate = _percent(row.get("hit_rate"))
    if rate is not None:
        lines.append(f"hit_rate={rate}")
    hits = _count(row.get("history_hits"))
    trades = _count(row.get("history_trades"))
    if hits is not None and trades is not None and trades > 0:
        lines.append(f"history={hits}/{trades}")
    return "\n".join(lines) or None


def _stars(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if 1 <= value <= 5:
        return value
    return None


def _percent(value: object) -> int | None:
    if isinstance(value, bool) or value is None or isinstance(value, str) and not value.strip():
        return None
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if amount < 0 or amount > 100:
        return None
    return int(amount.quantize(Decimal("1"), rounding="ROUND_HALF_UP"))


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _horizon(row: dict) -> str:
    raw = row.get("horizon", row.get("horizon_raw"))
    if isinstance(raw, str) and raw.strip():
        return " ".join(raw.split())[:80]
    return _DEFAULT_HORIZON


def _expires(horizon: str, published: datetime, trade_day: date) -> datetime:
    """Intraday lasts until the cash close. Any other horizon uses its own clock."""

    if not session_horizon(horizon):
        return _expires_at(horizon, published)
    close = datetime(trade_day.year, trade_day.month, trade_day.day, 15, 30, tzinfo=IST)
    if published >= close:
        return published
    return close


def _money(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None or isinstance(value, str) and not value.strip():
        return None
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if amount <= 0:
        return None
    return amount.quantize(_MONEY)


def _day(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _hhmm(raw: str) -> tuple[int, int] | None:
    parts = raw.strip().split(":")
    if len(parts) < 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def _auth_header(name: object) -> dict | None:
    if name in (None, ""):
        return {}
    secret = os.environ.get(str(name))
    if not secret:
        logger.info("http feed missing env %s", name)
        return None
    return {"Authorization": f"Bearer {secret}"}


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or "unknown"
