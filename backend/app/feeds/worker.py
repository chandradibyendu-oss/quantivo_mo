"""Documented entry point. The poller implementation is app.modules.feeds.worker."""

from app.modules.feeds.worker import main

if __name__ == "__main__":
    raise SystemExit(main())
