"""Telegram read. This is the only feed module that imports Telethon, and only when called."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC

from app.core.config import get_settings
from app.core.errors import AppError
from app.modules.feeds.service import ChannelPost


@dataclass(frozen=True)
class JoinedChannel:
    channel_id: str
    title: str


def _client():
    settings = get_settings()
    if not settings.telegram_login_configured:
        raise AppError(
            409,
            "telegram_login_missing",
            "The worker Telegram login is not configured.",
        )
    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise AppError(
            503,
            "telegram_reader_missing",
            "Install the feeds extra before polling Telegram.",
        ) from exc
    return TelegramClient(
        settings.telegram_session_path,
        int(settings.telegram_api_id),
        settings.telegram_api_hash,
    )


def _post(channel_id: str, row) -> ChannelPost | None:
    text = getattr(row, "message", None) or ""
    if not str(text).strip() or row.id is None or row.date is None:
        return None
    sent_at = row.date
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)
    return ChannelPost(
        channel_id=channel_id,
        message_id=int(row.id),
        sent_at=sent_at,
        text=str(text),
    )


async def _open():
    client = _client()
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise AppError(
            409,
            "telegram_login_missing",
            "The worker Telegram login is not authorized.",
        )
    return client


async def find_joined_channels(name: str) -> list[JoinedChannel]:
    """Match a channel title among chats this worker's login has already joined."""

    query = " ".join(name.split()).lower()
    if len(query) < 3:
        raise AppError(422, "invalid_feed_options", "Enter the Telegram channel name.")
    client = await _open()
    try:
        matches: list[JoinedChannel] = []
        async for dialog in client.iter_dialogs():
            if not dialog.is_channel:
                continue
            title = dialog.title or ""
            if query not in title.lower():
                continue
            matches.append(JoinedChannel(str(dialog.id), title))
            if len(matches) >= 20:
                break
        return matches
    except (OSError, sqlite3.Error) as exc:
        raise AppError(
            409,
            "telegram_login_busy",
            "The Telegram login is in use. Wait for the worker to finish its pass, then try again.",
        ) from exc
    finally:
        await client.disconnect()


async def fetch_recent(channel_id: str, limit: int) -> list[ChannelPost]:
    client = await _open()
    try:
        rows = await client.get_messages(int(channel_id), limit=limit)
        posts = [_post(channel_id, row) for row in rows]
        return [post for post in posts if post is not None]
    finally:
        await client.disconnect()


async def walk_history(channel_id: str, take) -> None:
    """Hand the channel's posts to `take` in batches. `take` stores them."""

    client = await _open()
    try:
        batch: list[ChannelPost] = []
        async for row in client.iter_messages(int(channel_id), limit=None):
            post = _post(channel_id, row)
            if post is None:
                continue
            batch.append(post)
            if len(batch) >= 200:
                take(batch)
                batch = []
        if batch:
            take(batch)
    finally:
        await client.disconnect()
