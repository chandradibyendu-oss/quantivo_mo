import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class CallClock(Base, TimestampMixin):
    """One row. Admin sets how old a call can be before it is stale."""

    __tablename__ = "call_clocks"
    __table_args__ = (
        CheckConstraint("intraday_minutes BETWEEN 1 AND 1440", name="intraday_minutes"),
        CheckConstraint("short_term_days BETWEEN 1 AND 365", name="short_term_days"),
        CheckConstraint("long_term_days BETWEEN 1 AND 365", name="long_term_days"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    intraday_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    short_term_days: Mapped[int] = mapped_column(Integer, nullable=False)
    long_term_days: Mapped[int] = mapped_column(Integer, nullable=False)


class Signal(Base, TimestampMixin):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("scanner_id", "external_ref", name="uq_signals_scanner_external_ref"),
        Index("ix_signals_scanner_published", "scanner_id", "published_at"),
        CheckConstraint("status IN ('active', 'expired', 'withdrawn')", name="status"),
        CheckConstraint("side IN ('BUY', 'SELL')", name="side"),
        CheckConstraint("timeframe IN ('INTRADAY', 'POSITIONAL')", name="timeframe"),
        CheckConstraint("product_hint IN ('MIS', 'CNC')", name="product_hint"),
        CheckConstraint("exchange IN ('NSE', 'BSE')", name="exchange"),
        CheckConstraint("trigger_price > 0 AND stop_loss > 0", name="prices_positive"),
        CheckConstraint("lot_size >= 1", name="lot_size"),
        CheckConstraint("segment IN ('equity', 'fno', 'commodity')", name="segment"),
        CheckConstraint("char_length(horizon_raw) > 0", name="horizon_raw"),
        CheckConstraint(
            "match_status IN ('matched', 'unmatched', 'ambiguous')",
            name="match_status",
        ),
        CheckConstraint("origin IN ('sample', 'channel')", name="origin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scanner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scanners.id", ondelete="CASCADE"), nullable=False
    )
    source_channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_channels.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    external_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    horizon_raw: Mapped[str] = mapped_column(String(80), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    product_hint: Mapped[str] = mapped_column(String(16), nullable=False)
    trigger_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    targets: Mapped[list] = mapped_column(JSONB, nullable=False)
    provider_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    lot_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    match_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="matched", server_default="matched"
    )
    origin: Mapped[str] = mapped_column(
        String(16), nullable=False, default="sample", server_default="sample"
    )
