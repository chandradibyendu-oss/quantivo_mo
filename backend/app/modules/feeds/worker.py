"""Poll Telegram channels configured in this database. Run one copy of this process."""

import asyncio
import logging
import time
from datetime import datetime

import app.models  # noqa: F401  — register every table before a signal is saved
from app.core.config import get_settings
from app.core.database import get_session_factory, utcnow
from app.core.logging import configure_logging
from app.modules.feeds.http_source import fetch_json
from app.modules.feeds.normalize import rematch_channel_names
from app.modules.feeds.pdl_sweep import poll_http_feeds
from app.modules.feeds.service import poll_telegram_feeds
from app.modules.feeds.telegram_source import fetch_recent, walk_history
from app.modules.feeds.window import in_equity_window

logger = logging.getLogger("quantivo.feeds")
_http_polled: dict = {}


def pause_seconds(moment: datetime | None = None) -> int:
    """Check often while the equity window is open, and once a minute outside it."""
    return 5 if in_equity_window(moment or utcnow()) else 60


def _fetch(channel_id: str, limit: int):
    return asyncio.run(fetch_recent(channel_id, limit))


def _history(channel_id: str, take) -> None:
    asyncio.run(walk_history(channel_id, take))


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    session = get_session_factory()()
    try:
        changed = rematch_channel_names(session)
        session.commit()
        logger.info("nse name rematch updated=%s", changed)
    except Exception:
        session.rollback()
        logger.exception("nse name rematch failed")
    finally:
        session.close()
    while True:
        session = get_session_factory()()
        try:
            report = poll_telegram_feeds(session, _fetch, fetch_history=_history)
            http_report = poll_http_feeds(
                session, fetch_json, now=utcnow(), last_polled=_http_polled
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        if report.login in {"unused", "not_configured"} and http_report.channels == 0:
            if report.login == "unused":
                logger.info("No active Telegram feed is configured.")
            else:
                logger.info(
                    "Telegram login is not configured on this worker. "
                    "Set TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_SESSION_PATH here. "
                    "Nothing is read from another project."
                )
            return 0
        if http_report.channels:
            logger.info(
                "http channels=%s created=%s unchanged=%s revised=%s skipped=%s",
                http_report.channels,
                http_report.created,
                http_report.unchanged,
                http_report.revised,
                http_report.skipped,
            )
        if report.login in {"unused", "not_configured"}:
            time.sleep(pause_seconds())
            continue
        logger.info(
            "telegram channels=%s created=%s unchanged=%s revised=%s skipped=%s",
            report.channels,
            report.created,
            report.unchanged,
            report.revised,
            report.skipped,
        )
        time.sleep(pause_seconds())


if __name__ == "__main__":
    raise SystemExit(main())
