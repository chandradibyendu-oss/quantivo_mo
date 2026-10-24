from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.modules.progress.history import clear_history_cache, parse_fyers_candles, remember_day
from app.modules.progress.marks import apply_progress
from app.modules.signals.schemas import ProviderValues, QuantivoValues, SignalCard, TargetOut

IST = ZoneInfo("Asia/Kolkata")


def _card() -> SignalCard:
    return SignalCard(
        id=uuid4(),
        symbol="SBIN",
        exchange="NSE",
        side="BUY",
        timeframe="POSITIONAL",
        product_hint="CNC",
        status="active",
        stored_status="active",
        warning=None,
        executable=True,
        guide="window_over",
        guide_label="Window over",
        guide_hint="The entry window has ended.",
        published_at=datetime(2026, 10, 23, 10, 0, tzinfo=IST),
        expires_at=datetime(2026, 11, 22, 10, 0, tzinfo=IST),
        provider_name="Mani's",
        scanner_id=uuid4(),
        scanner_name="Mani's Channel",
        segment="equity",
        channel_code="equity",
        channel_name="Equity",
        horizon_raw="Short term",
        lot_size=1,
        provider_values=ProviderValues(
            trigger_price="100.00",
            stop_loss="90.00",
            targets=[TargetOut(label="T1", price="110.00"), TargetOut(label="T2", price="120.00")],
            note=None,
        ),
        quantivo_values=QuantivoValues(
            suggested_quantity=12,
            per_share_risk="10.00",
            estimated_risk_inr="120.00",
            notional_inr="1200.00",
            capital_allocation_inr="100000.00",
            max_risk_inr="500.00",
            formula="floor(maximum rupee risk / per-share risk)",
            funds_check="not_checked",
            unavailable_reason=None,
        ),
        suggested_quantity=12,
    )


def _use_bars(monkeypatch):
    monkeypatch.setattr(
        "app.modules.progress.marks.get_settings",
        lambda: SimpleNamespace(fyers_quotes_configured=True),
    )
    monkeypatch.setattr(
        "app.modules.progress.marks.fyers_code",
        lambda _exchange, _symbol: "NSE:SBIN-EQ",
    )


def _bar(minute: int, high: str, low: str, close: str):
    return (
        datetime(2026, 10, 23, 10, minute, tzinfo=IST),
        Decimal(high),
        Decimal(low),
        Decimal(close),
    )


def test_fyers_candles_keep_the_high_low_and_close():
    opened = datetime(2026, 10, 23, 10, 4, tzinfo=IST)
    body = (
        '{"s":"ok","candles":[['
        f"{int(opened.timestamp())},100,111,99,105.5,10"
        "]]}"
    )
    bars = parse_fyers_candles(body)
    assert bars is not None
    assert bars[0][1:4] == (Decimal("111"), Decimal("99"), Decimal("105.5"))
    assert bars[0][4] == Decimal("100")


def test_the_entry_minute_is_shown_and_quantity_stays(monkeypatch):
    _use_bars(monkeypatch)
    remember_day(
        "NSE:SBIN-EQ",
        date(2026, 10, 23),
        [_bar(4, "111", "99", "105")],
        now=datetime(2026, 10, 23, 12, 0, tzinfo=IST),
        retry=None,
    )
    try:
        painted = apply_progress([_card()], now=datetime(2026, 10, 23, 10, 20, tzinfo=IST))
    finally:
        clear_history_cache()
    assert painted[0].guide == "entry"
    assert painted[0].guide_label == "Entry 10:05"
    assert "entry" in painted[0].guide_hint.lower()
    assert painted[0].suggested_quantity == 12
    assert painted[0].executable is True


def test_not_valid_when_the_window_was_read_and_price_never_closed_through(monkeypatch):
    _use_bars(monkeypatch)
    remember_day(
        "NSE:SBIN-EQ",
        date(2026, 10, 23),
        [_bar(10, "101", "98", "100"), _bar(29, "101", "98", "100")],
        now=datetime(2026, 10, 23, 16, 0, tzinfo=IST),
        retry=None,
    )
    try:
        painted = apply_progress([_card()], now=datetime(2026, 10, 23, 16, 0, tzinfo=IST))
    finally:
        clear_history_cache()
    assert painted[0].guide == "not_valid"
    assert painted[0].executable is False


def test_stop_shows_the_minute_after_entry(monkeypatch):
    _use_bars(monkeypatch)
    remember_day(
        "NSE:SBIN-EQ",
        date(2026, 10, 23),
        [_bar(4, "111", "99", "105"), _bar(40, "106", "89", "95")],
        now=datetime(2026, 10, 23, 16, 0, tzinfo=IST),
        retry=None,
    )
    try:
        painted = apply_progress([_card()], now=datetime(2026, 10, 23, 16, 0, tzinfo=IST))
    finally:
        clear_history_cache()
    assert painted[0].guide == "stop"
    assert painted[0].guide_label == "Stop 10:40"
    assert painted[0].executable is False
    assert painted[0].suggested_quantity == 12


def test_without_fyers_the_clock_mark_stays(monkeypatch):
    monkeypatch.setattr(
        "app.modules.progress.marks.get_settings",
        lambda: SimpleNamespace(fyers_quotes_configured=False),
    )
    painted = apply_progress([_card()], now=datetime(2026, 10, 24, 12, 0, tzinfo=IST))
    assert painted[0].guide == "window_over"
    assert painted[0].suggested_quantity == 12
