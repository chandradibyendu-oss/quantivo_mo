"""Read and save finished one-minute bars. The forming minute is not written."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.database import get_session_factory
from app.modules.progress.models import MinuteBar, MinuteBarDay

Bar = tuple[datetime, Decimal, Decimal, Decimal] | tuple


def load_saved(code: str, day: date) -> tuple[list[Bar] | None, bool]:
    """Bars for one symbol-day, and whether that day is complete. None when nothing is saved."""

    session = get_session_factory()()
    try:
        marker = session.get(MinuteBarDay, (code, day))
        rows = session.scalars(
            select(MinuteBar)
            .where(MinuteBar.symbol == code, MinuteBar.session_date == day)
            .order_by(MinuteBar.opened_at)
        ).all()
    finally:
        session.close()
    if not rows and marker is None:
        return None, False
    bars = [
        (row.opened_at, row.high, row.low, row.close, row.open)
        for row in rows
    ]
    return bars, bool(marker and marker.complete)


def save_bars(code: str, day: date, bars: list[Bar], *, complete: bool) -> None:
    """Upsert finished minutes. A complete day is not requested from Fyers again."""

    if not bars and not complete:
        return
    session = get_session_factory()()
    try:
        if bars:
            _upsert_bars(session, code, day, bars)
        if complete:
            _mark_complete(session, code, day)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _upsert_bars(session: Session, code: str, day: date, bars: list[Bar]) -> None:
    values = []
    for bar in bars:
        opened = bar[0]
        opened_price = bar[4] if len(bar) > 4 else bar[3]
        values.append(
            {
                "symbol": code,
                "opened_at": opened,
                "session_date": day,
                "open": Decimal(opened_price),
                "high": Decimal(bar[1]),
                "low": Decimal(bar[2]),
                "close": Decimal(bar[3]),
            }
        )
    statement = insert(MinuteBar).values(values)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["symbol", "opened_at"],
            set_={
                "open": statement.excluded.open,
                "high": statement.excluded.high,
                "low": statement.excluded.low,
                "close": statement.excluded.close,
                "session_date": statement.excluded.session_date,
            },
        )
    )


def _mark_complete(session: Session, code: str, day: date) -> None:
    statement = insert(MinuteBarDay).values(symbol=code, session_date=day, complete=True)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["symbol", "session_date"],
            set_={"complete": True},
        )
    )
