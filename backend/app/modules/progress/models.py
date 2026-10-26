"""Saved one-minute bars. A bar is not a column on the signal."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MinuteBar(Base):
    """One finished minute for one NSE cash symbol."""

    __tablename__ = "minute_bars"
    __table_args__ = (Index("ix_minute_bars_symbol_session_date", "symbol", "session_date"),)

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)


class MinuteBarDay(Base):
    """A session whose bars were read in full and are not requested again."""

    __tablename__ = "minute_bar_days"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_date: Mapped[date] = mapped_column(Date, primary_key=True)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
