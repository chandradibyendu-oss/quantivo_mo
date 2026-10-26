from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.modules.progress.path import assess_path

IST = timezone(timedelta(hours=5, minutes=30))
SENT = datetime(2026, 10, 23, 10, 0, tzinfo=IST)


def _bar(minute: int, high: str, low: str, close: str, hour: int = 10):
    opened = datetime(2026, 10, 23, hour, minute, tzinfo=IST)
    return opened, Decimal(high), Decimal(low), Decimal(close)


def _assess(bars, *, now_minute: int = 20, targets=("124", "126", "128"), covered=True, side="BUY"):
    return assess_path(
        side=side,
        trigger=Decimal("123"),
        stop=Decimal("120"),
        targets=[Decimal(price) for price in targets],
        published_at=SENT,
        bars=bars,
        now=datetime(2026, 10, 23, 10, now_minute, tzinfo=IST),
        covered=covered,
    )


def test_a_wick_through_the_trigger_is_not_an_entry():
    mark = _assess([_bar(1, "124", "121", "122.5")], now_minute=10)
    assert mark is not None
    assert mark.code == "waiting"


def test_a_sell_enters_when_the_one_minute_candle_closes_below_the_trigger():
    mark = _assess([_bar(4, "123.2", "121", "122.4")], now_minute=10, side="SELL")
    assert mark is not None
    assert mark.code == "entry"
    assert mark.at == datetime(2026, 10, 23, 10, 5, tzinfo=IST)


def test_waiting_while_the_window_is_open_and_price_has_not_closed_through():
    mark = _assess([_bar(1, "122", "121", "121.5")], now_minute=10)
    assert mark is not None
    assert mark.code == "waiting"


def test_caution_when_the_stop_is_touched_before_a_close_through():
    mark = _assess([_bar(2, "122", "119.5", "121")], now_minute=10)
    assert mark is not None
    assert mark.code == "caution"
    assert mark.at == datetime(2026, 10, 23, 10, 2, tzinfo=IST)


def test_a_stop_touch_before_a_later_close_is_not_an_entry():
    bars = [
        _bar(2, "122", "119.5", "121"),
        _bar(8, "124", "122", "123.4"),
    ]
    mark = _assess(bars, now_minute=20)
    assert mark is not None
    assert mark.code == "caution"
    assert mark.at == datetime(2026, 10, 23, 10, 2, tzinfo=IST)


def test_not_valid_when_the_window_ends_with_no_close_through():
    mark = _assess([_bar(5, "122.5", "121", "122")], now_minute=40)
    assert mark is not None
    assert mark.code == "not_valid"


def test_entry_is_the_minute_the_one_minute_candle_closed_through():
    mark = _assess([_bar(4, "124", "122", "123.4")], now_minute=10)
    assert mark is not None
    assert mark.code == "entry"
    assert mark.at == datetime(2026, 10, 23, 10, 5, tzinfo=IST)


def test_t1_trail_then_final_on_the_last_target():
    bars = [
        _bar(4, "124", "122", "123.4"),
        _bar(8, "124.2", "123", "124"),
        _bar(12, "128.4", "124", "128"),
    ]
    mark = _assess(bars, now_minute=20, targets=("124", "128"))
    assert mark is not None
    assert mark.code == "final"
    assert mark.at == datetime(2026, 10, 23, 10, 12, tzinfo=IST)


def test_t2_is_a_trail_only_when_a_later_target_remains():
    bars = [
        _bar(4, "124", "122", "123.4"),
        _bar(9, "126.2", "124", "126"),
    ]
    mark = _assess(bars, now_minute=20, targets=("124", "126", "130"))
    assert mark is not None
    assert mark.code == "t2_trail"
    assert mark.level == "T2"


def test_a_bar_that_hits_the_stop_and_a_target_does_not_choose():
    bars = [
        _bar(4, "124", "122", "123.4"),
        _bar(9, "126", "119", "121"),
    ]
    mark = _assess(bars, now_minute=20)
    assert mark is not None
    assert mark.code == "entry"


def test_stop_after_entry_when_a_later_bar_only_touches_the_stop():
    bars = [
        _bar(4, "124", "122", "123.4"),
        _bar(11, "123.2", "119.8", "120.4"),
    ]
    mark = _assess(bars, now_minute=20)
    assert mark is not None
    assert mark.code == "stop"
    assert mark.at == datetime(2026, 10, 23, 10, 11, tzinfo=IST)
