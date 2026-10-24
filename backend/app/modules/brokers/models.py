import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, utcnow


class BrokerConnection(Base, TimestampMixin):
    """Connection state only. Broker passwords, OTPs, access tokens, and API secrets are not stored."""

    __tablename__ = "broker_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "broker_code", name="uq_broker_connections_user_broker"),
        CheckConstraint(
            "status IN ('disconnected', 'connected', 'expired', 'unavailable')",
            name="status",
        ),
        {"comment": "No broker passwords, OTPs, access tokens, or API secrets are stored in this table."},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    broker_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    external_account_ref: Mapped[str | None] = mapped_column(String(128))
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_message: Mapped[str | None] = mapped_column(String(255))


class BrokerAccount(Base, TimestampMixin):
    __tablename__ = "broker_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("broker_connections.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    external_account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    segments: Mapped[list] = mapped_column(JSONB, nullable=False)


class PositionSnapshot(Base):
    """Broker-reported position fact. Internal intent must not overwrite these rows."""

    __tablename__ = "position_snapshots"
    __table_args__ = (
        CheckConstraint("source IN ('broker', 'reconciliation')", name="source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    broker_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("broker_connections.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    product: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    average_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
