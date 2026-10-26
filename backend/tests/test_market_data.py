from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.modules.progress.bars import save_bars
from app.modules.progress.history import (
    _persist_enabled,
    _retain,
    clear_history_cache,
    day_state,
    note_print,
    remember_day,
)
from app.modules.progress.models import MinuteBar
from app.modules.quotes.budget import (
    HISTORY_PER_MINUTE,
    PER_DAY,
    clear_data_budget,
    data_paused,
    note_rate_limit,
    set_pause_jitter,
    take_data_slot,
)
from app.modules.quotes.live import remember_tick
from sqlalchemy import func, select

IST_OFFSET = datetime(2026, 10, 26, 4, 0, tzinfo=UTC)


def test_history_keeps_room_in_the_minute_for_a_quote():
    now = IST_OFFSET
    try:
        for step in range(HISTORY_PER_MINUTE):
            assert take_data_slot("history", now + timedelta(milliseconds=250 * step))
        later = now + timedelta(seconds=12)
        assert take_data_slot("history", later) is False
        assert take_data_slot("quotes", later) is True
    finally:
        clear_data_budget()


def test_a_rate_limit_backs_off_and_then_allows_another_call():
    now = IST_OFFSET
    set_pause_jitter(lambda: 0)
    try:
        note_rate_limit(now)
        assert data_paused(now + timedelta(seconds=5))
        assert take_data_slot("quotes", now + timedelta(seconds=5)) is False
        assert data_paused(now + timedelta(seconds=31)) is False
        assert take_data_slot("history", now + timedelta(seconds=31)) is True
    finally:
        set_pause_jitter(lambda: __import__("random").uniform(0, 5))
        clear_data_budget()


def test_the_day_allowance_is_shared():
    now = IST_OFFSET
    try:
        for step in range(PER_DAY):
            assert take_data_slot("quotes", now + timedelta(seconds=2 * step))
        blocked = now + timedelta(seconds=2 * PER_DAY)
        assert take_data_slot("quotes", blocked) is False
        assert take_data_slot("history", blocked) is False
    finally:
        clear_data_budget()


def test_a_failed_refresh_keeps_the_bars_already_read():
    code = "NSE:SBIN-EQ"
    day = datetime(2026, 10, 23, tzinfo=UTC).date()
    remember_day(
        code,
        day,
        [(datetime(2026, 10, 23, 10, 4, tzinfo=UTC), Decimal("1"), Decimal("1"), Decimal("1"))],
        now=datetime(2026, 10, 23, 10, 0, tzinfo=UTC),
        retry=timedelta(seconds=60),
    )
    try:
        _retain(code, day, timedelta(minutes=15))
        _state, bars = day_state(code, day, datetime.now(UTC))
        assert bars
        assert bars[0][3] == Decimal("1")
    finally:
        clear_history_cache()


def test_a_socket_message_keeps_the_percent_from_the_previous_close():
    from app.modules.quotes.live import clear_live, fresh_ticks

    now = IST_OFFSET
    remember_tick({"symbol": "NSE:SBIN-EQ", "ltp": "110", "prev_close_price": "100"}, now)
    try:
        found = fresh_ticks({"NSE:SBIN-EQ"}, now)
    finally:
        clear_live()
    assert found["NSE:SBIN-EQ"].price == Decimal("110")
    assert found["NSE:SBIN-EQ"].change_percent == Decimal("10.00")


def test_a_saved_day_is_ready_after_the_process_forgets_it(db, monkeypatch):
    monkeypatch.setattr("app.modules.progress.history._persist_enabled", lambda: True)
    code = "NSE:SBIN-EQ"
    day = datetime(2026, 10, 23, tzinfo=UTC).date()
    opened = datetime(2026, 10, 23, 4, 34, tzinfo=UTC)
    save_bars(
        code,
        day,
        [(opened, Decimal("12"), Decimal("10"), Decimal("11"), Decimal("10.5"))],
        complete=True,
    )
    try:
        clear_history_cache()
        state, bars = day_state(code, day, datetime(2026, 10, 26, 5, tzinfo=UTC))
        assert state == "ready"
        assert bars[0][1:] == (Decimal("12"), Decimal("10"), Decimal("11"), Decimal("10.5"))
        clear_history_cache()
        assert db.scalar(select(func.count()).select_from(MinuteBar)) == 1
        state, bars = day_state(code, day, datetime(2026, 10, 26, 5, tzinfo=UTC))
        assert state == "ready"
        assert bars[0][3] == Decimal("11")
    finally:
        clear_history_cache()
        monkeypatch.setattr("app.modules.progress.history._persist_enabled", _persist_enabled)


def test_a_finished_socket_minute_is_saved_and_the_open_minute_is_not(db, monkeypatch):
    monkeypatch.setattr("app.modules.progress.history._persist_enabled", lambda: True)
    code = "NSE:HAVELLS-EQ"
    start = datetime(2026, 10, 26, 4, 30, tzinfo=UTC)
    day = datetime(2026, 10, 26, tzinfo=UTC).date()
    try:
        note_print(code, Decimal("100"), start)
        note_print(code, Decimal("110"), start + timedelta(seconds=20))
        note_print(code, Decimal("90"), start + timedelta(minutes=1))
        saved = db.scalars(select(MinuteBar).where(MinuteBar.symbol == code)).all()
        assert len(saved) == 1
        assert saved[0].high == Decimal("110")
        assert saved[0].close == Decimal("110")
        assert saved[0].low == Decimal("100")
        state, bars = day_state(code, day, start + timedelta(minutes=1, seconds=5))
        assert state == "stale"
        assert {bar[3] for bar in bars} == {Decimal("110"), Decimal("90")}
    finally:
        clear_history_cache()


def test_a_failed_refresh_leaves_the_saved_day_in_place(db, monkeypatch):
    monkeypatch.setattr("app.modules.progress.history._persist_enabled", lambda: True)
    code = "NSE:TCS-EQ"
    day = datetime(2026, 10, 22, tzinfo=UTC).date()
    opened = datetime(2026, 10, 22, 4, 20, tzinfo=UTC)
    save_bars(
        code,
        day,
        [(opened, Decimal("3"), Decimal("2"), Decimal("2.5"), Decimal("2"))],
        complete=True,
    )
    try:
        clear_history_cache()
        _retain(code, day, timedelta(minutes=15))
        clear_history_cache()
        state, bars = day_state(code, day, datetime(2026, 10, 26, 5, tzinfo=UTC))
        assert state == "ready"
        assert bars[0][3] == Decimal("2.5")
        assert db.scalar(select(func.count()).select_from(MinuteBar)) == 1
    finally:
        clear_history_cache()
