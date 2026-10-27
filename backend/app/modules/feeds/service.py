"""Read and save channel feed settings, and ingest posts the worker already fetched."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.errors import AppError
from app.modules.audit.service import record
from app.modules.feeds.equity_parser import continue_equity_call, parse_equity_call
from app.modules.feeds.models import SourceFeed
from app.modules.feeds.normalize import external_ref_for, to_signal
from app.modules.feeds.options import validate_feed_options
from app.modules.feeds.window import in_equity_window
from app.modules.scanners.models import Scanner, SourceChannel
from app.modules.signals.service import IngestOutcome, ingest

logger = logging.getLogger("quantivo.feeds")

# The next Telegram message can complete a call only when it is posted immediately after.
_FOLLOW_UP = timedelta(minutes=10)


@dataclass(frozen=True)
class ChannelPost:
    channel_id: str
    message_id: int
    sent_at: datetime
    text: str


@dataclass(frozen=True)
class PollReport:
    login: str
    channels: int
    created: int
    unchanged: int
    revised: int
    skipped: int


def list_feeds(db: Session) -> list[tuple[SourceChannel, Scanner, SourceFeed]]:
    rows = db.execute(
        select(SourceChannel, Scanner, SourceFeed)
        .join(Scanner, Scanner.id == SourceChannel.scanner_id)
        .join(SourceFeed, SourceFeed.source_channel_id == SourceChannel.id)
        .order_by(Scanner.name, SourceChannel.name)
    ).all()
    return [(channel, scanner, feed) for channel, scanner, feed in rows]


def save_feed(
    db: Session,
    *,
    channel_id,
    kind: str,
    status: str,
    options: dict,
    actor_user_id,
    correlation_id: str | None,
) -> tuple[SourceChannel, Scanner, SourceFeed]:
    row = db.execute(
        select(SourceChannel, Scanner)
        .join(Scanner, Scanner.id == SourceChannel.scanner_id)
        .where(SourceChannel.id == channel_id)
    ).one_or_none()
    if row is None:
        raise AppError(404, "channel_not_found", "That source channel is not in the catalogue.")
    channel, scanner = row
    if kind not in {"none", "telegram", "http_api"}:
        raise AppError(422, "invalid_feed_kind", "Choose none, telegram, or http_api.")
    if status not in {"active", "inactive"}:
        raise AppError(422, "invalid_feed_status", "Choose active or inactive.")
    cleaned = validate_feed_options(kind, options, segment=channel.segment)
    feed = db.scalar(select(SourceFeed).where(SourceFeed.source_channel_id == channel.id))
    previous_channel = None if feed is None else (feed.options or {}).get("channel_id")
    if feed is None:
        feed = SourceFeed(source_channel_id=channel.id, kind=kind, status=status, options=cleaned)
        db.add(feed)
    else:
        feed.kind = kind
        feed.status = status
        feed.options = cleaned
        if kind != "telegram" or cleaned.get("channel_id") != previous_channel:
            feed.history_synced_at = None
    db.flush()
    record(
        db,
        action="feed.configured",
        entity_type="source_feed",
        entity_id=feed.id,
        payload=_audit_payload(channel, kind, status, cleaned),
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
    )
    return channel, scanner, feed


def telegram_login_status() -> tuple[str, str]:
    """Whether this worker can read Telegram. The values themselves are not returned."""

    if get_settings().telegram_login_configured:
        return (
            "present",
            "One Telegram login on this worker is used for every Telegram channel. "
            "The phone, API id, API hash, and session stay on the worker.",
        )
    return (
        "missing",
        "This worker has no Telegram login yet. One login will cover every Telegram channel. "
        "It is not entered here.",
    )


def reader_state(feed: SourceFeed) -> tuple[str, str]:
    if feed.kind == "none":
        return (
            "sample",
            "This channel uses the development sample until an operator selects a feed.",
        )
    if feed.kind == "http_api":
        return (
            "saved",
            "The worker reads this URL. Intraday is the horizon when the payload omits one. "
            "That call stays on Actionable through its IST trade date, then it is on All.",
        )
    if get_settings().telegram_login_configured:
        return (
            "login_present",
            "This worker has its own Telegram login values. They are not included here.",
        )
    return (
        "login_not_configured",
        "Set TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_SESSION_PATH on the worker. "
        "They are not stored in this database.",
    )


def scanner_feed_mode(db: Session, scanner_id) -> str:
    """How the phone should read this scanner. Sample calls stay only while the kind is none."""

    feeds = db.scalars(
        select(SourceFeed)
        .join(SourceChannel, SourceChannel.id == SourceFeed.source_channel_id)
        .where(
            SourceChannel.scanner_id == scanner_id,
            SourceChannel.status == "active",
            SourceFeed.status == "active",
            SourceFeed.kind == "telegram",
        )
    ).all()
    if not feeds:
        return "mock"
    if get_settings().telegram_login_configured:
        return "telegram"
    return "telegram_pending"


def poll_telegram_feeds(
    db: Session,
    fetch,
    *,
    fetch_history=None,
    login_ready: bool | None = None,
) -> PollReport:
    """Ingest active Telegram channels. History runs once, then each pass reads recent posts."""

    feeds = db.scalars(
        select(SourceFeed).where(SourceFeed.kind == "telegram", SourceFeed.status == "active")
    ).all()
    if not feeds:
        return PollReport("unused", 0, 0, 0, 0, 0)
    ready = get_settings().telegram_login_configured if login_ready is None else login_ready
    if not ready:
        return PollReport("not_configured", len(feeds), 0, 0, 0, 0)

    created = unchanged = revised = skipped = 0
    for feed in feeds:
        channel = db.get(SourceChannel, feed.source_channel_id)
        if channel is None or channel.status != "active":
            skipped += 1
            continue
        options = feed.options or {}
        if options.get("parser") != "equity_calls" or channel.segment != "equity":
            skipped += 1
            continue
        channel_ref = str(options["channel_id"])
        if feed.history_synced_at is None and fetch_history is not None:
            tally = {"created": 0, "unchanged": 0, "revised": 0, "skipped": 0}
            carried: list[ChannelPost] = []

            def take(batch: list[ChannelPost]) -> None:
                # History arrives newest first. Keep the oldest post so the next
                # older batch can still see the message posted immediately after it.
                context_ids = {item.message_id for item in carried}
                _count_posts(
                    db,
                    channel,
                    [*batch, *carried],
                    tally,
                    context_ids=context_ids,
                )
                carried.clear()
                if batch:
                    carried.append(min(batch, key=lambda item: item.message_id))
                db.commit()
                logger.info(
                    "telegram history batch channel=%s created=%s unchanged=%s "
                    "revised=%s skipped=%s",
                    channel.code,
                    tally["created"],
                    tally["unchanged"],
                    tally["revised"],
                    tally["skipped"],
                )

            fetch_history(channel_ref, take)
            feed.history_synced_at = utcnow()
            created += tally["created"]
            unchanged += tally["unchanged"]
            revised += tally["revised"]
            skipped += tally["skipped"]
            continue
        posts = fetch(channel_ref, int(options.get("poll_limit", 40)))
        tally = {"created": 0, "unchanged": 0, "revised": 0, "skipped": 0}
        _count_posts(db, channel, posts, tally)
        created += tally["created"]
        unchanged += tally["unchanged"]
        revised += tally["revised"]
        skipped += tally["skipped"]
    return PollReport("used", len(feeds), created, unchanged, revised, skipped)


def _count_posts(
    db: Session,
    channel: SourceChannel,
    posts: list[ChannelPost],
    tally: dict,
    context_ids: set[int] | None = None,
) -> None:
    context = context_ids or set()
    ordered = sorted(posts, key=lambda post: post.message_id)
    used_follow_up: set[int] = set()
    for index, post in enumerate(ordered):
        if post.message_id in context:
            continue
        if post.message_id in used_follow_up:
            tally["skipped"] += 1
            continue
        follow_up = ordered[index + 1] if index + 1 < len(ordered) else None
        outcome, consumed = _ingest_post(db, channel, post, follow_up)
        if consumed and follow_up is not None:
            used_follow_up.add(follow_up.message_id)
        if outcome is None:
            tally["skipped"] += 1
        elif outcome is IngestOutcome.CREATED:
            tally["created"] += 1
        elif outcome is IngestOutcome.REVISED:
            tally["revised"] += 1
        else:
            tally["unchanged"] += 1


def _ingest_post(
    db: Session,
    channel: SourceChannel,
    post: ChannelPost,
    follow_up: ChannelPost | None = None,
) -> tuple[IngestOutcome | None, bool]:
    if not in_equity_window(post.sent_at):
        return None, False
    parsed = parse_equity_call(post.text)
    consumed = False
    if parsed is None:
        nxt = _immediate_follow_up(post, follow_up)
        if nxt is not None:
            parsed = continue_equity_call(post.text, nxt.text)
            consumed = parsed is not None
    if parsed is None:
        return None, False
    try:
        ref = external_ref_for(post.channel_id, post.message_id)
    except ValueError:
        return None, False
    draft = to_signal(parsed, channel=channel, external_ref=ref, published_at=post.sent_at)
    outcome = ingest(
        db,
        scanner_id=channel.scanner_id,
        draft=draft,
        correlation_id="feed-worker",
    )
    return outcome, consumed


def _immediate_follow_up(post: ChannelPost, follow_up: ChannelPost | None) -> ChannelPost | None:
    if follow_up is None or follow_up.channel_id != post.channel_id:
        return None
    if follow_up.message_id != post.message_id + 1:
        return None
    gap = _aware(follow_up.sent_at) - _aware(post.sent_at)
    if gap < timedelta(0) or gap > _FOLLOW_UP:
        return None
    return follow_up


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def _audit_payload(channel: SourceChannel, kind: str, status: str, options: dict) -> dict:
    payload: dict = {"kind": kind, "status": status, "channel_code": channel.code}
    if kind == "telegram":
        payload["channel_ref"] = options.get("channel_id")
    elif kind == "http_api":
        host = urlparse(str(options.get("url", ""))).hostname
        payload["host"] = host
    return payload
