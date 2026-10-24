from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.modules.feeds.window import quote_label
from app.modules.progress.candles import session_candles
from app.modules.progress.history import clear_history_cache, remember_day

IST = ZoneInfo("Asia/Kolkata")


def _bar(minute: int, high: str, low: str, close: str, open_price: str):
    return (
        datetime(2026, 10, 23, 9, minute, tzinfo=IST),
        Decimal(high),
        Decimal(low),
        Decimal(close),
        Decimal(open_price),
    )


def test_the_label_is_ltp_only_during_the_cash_session():
    assert quote_label(datetime(2026, 10, 23, 10, 0, tzinfo=IST)) == "LTP"
    assert quote_label(datetime(2026, 10, 24, 12, 0, tzinfo=IST)) == "Last LTP"
    assert quote_label(datetime(2026, 10, 23, 16, 0, tzinfo=IST)) == "Last LTP"


def test_five_minute_candles_fold_the_session_minutes(monkeypatch):
    monkeypatch.setattr(
        "app.modules.progress.candles.get_settings",
        lambda: SimpleNamespace(fyers_quotes_configured=True),
    )
    monkeypatch.setattr(
        "app.modules.progress.candles.fyers_code",
        lambda _exchange, _symbol: "NSE:SBIN-EQ",
    )
    remember_day(
        "NSE:SBIN-EQ",
        datetime(2026, 10, 23, tzinfo=IST).date(),
        [
            _bar(15, "102", "99", "101", "100"),
            _bar(16, "104", "100", "103", "101"),
            _bar(19, "105", "102", "104", "103"),
        ],
        now=datetime(2026, 10, 23, 16, 0, tzinfo=IST),
        retry=None,
    )
    try:
        state, candles = session_candles(
            exchange="NSE",
            symbol="SBIN",
            segment="equity",
            interval="5m",
            now=datetime(2026, 10, 24, 12, 0, tzinfo=IST),
        )
    finally:
        clear_history_cache()
    assert state == "ready"
    assert candles == [
        {"time": "09:15", "open": "100", "high": "105", "low": "99", "close": "104"}
    ]


def test_without_fyers_the_chart_has_no_candles(monkeypatch):
    monkeypatch.setattr(
        "app.modules.progress.candles.get_settings",
        lambda: SimpleNamespace(fyers_quotes_configured=False),
    )
    state, candles = session_candles(
        exchange="NSE",
        symbol="SBIN",
        segment="equity",
        interval="1m",
        now=datetime(2026, 10, 24, 12, 0, tzinfo=IST),
    )
    assert state == "unconfigured"
    assert candles == []
