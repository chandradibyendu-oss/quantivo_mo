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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, utcnow

_INTENT_STATUSES = (
    "proposed",
    "awaiting_confirmation",
    "submitted",
    "accepted",
    "rejected",
    "partially_filled",
    "filled",
    "protection_pending",
    "protected",
    "exit_pending",
    "closed",
    "cancelled",
    "failed",
)


class OrderIntent(Base, TimestampMixin):
    """What the trader confirmed. This build stores it and does not send it to a broker."""

    __tablename__ = "order_intents"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{status}'" for status in _INTENT_STATUSES) + ")",
            name="status",
        ),
        CheckConstraint("product IN ('MIS', 'CNC')", name="product"),
        CheckConstraint("side IN ('BUY', 'SELL')", name="side"),
        CheckConstraint("trigger_price > 0 AND stop_loss > 0", name="prices_positive"),
        CheckConstraint("requested_quantity > 0", name="requested_quantity"),
        CheckConstraint(
            "validated_quantity IS NULL OR validated_quantity > 0",
            name="validated_quantity",
        ),
        Index(
            "uq_order_intents_open_signal",
            "user_id",
            "signal_id",
            unique=True,
            postgresql_where=text("status = 'proposed'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    product: Mapped[str] = mapped_column(String(16), nullable=False)
    trigger_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    targets: Mapped[list] = mapped_column(JSONB, nullable=False)
    requested_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    validated_quantity: Mapped[int | None] = mapped_column(Integer)
    rejection_reason: Mapped[str | None] = mapped_column(String(255))


class BrokerOrder(Base, TimestampMixin):
    __tablename__ = "broker_orders"
    __table_args__ = (
        UniqueConstraint(
            "broker_connection_id",
            "broker_order_id",
            name="uq_broker_orders_connection_external",
        ),
        CheckConstraint("role IN ('entry', 'stop_loss', 'target')", name="role"),
        CheckConstraint(
            "status IN ('pending_submit', 'open', 'partially_filled', 'filled', 'cancelled', 'rejected', 'unknown')",
            name="status",
        ),
        CheckConstraint("quantity > 0", name="quantity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_intent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_intents.id", ondelete="CASCADE"), nullable=False
    )
    broker_connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("broker_connections.id", ondelete="RESTRICT"), nullable=False
    )
    broker_order_id: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))


class TradeExecution(Base):
    __tablename__ = "trade_executions"
    __table_args__ = (
        UniqueConstraint(
            "broker_order_id",
            "external_trade_id",
            name="uq_trade_executions_order_trade",
        ),
        CheckConstraint("quantity > 0", name="quantity"),
        CheckConstraint("price > 0", name="price"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broker_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("broker_orders.id", ondelete="CASCADE"), nullable=False
    )
    external_trade_id: Mapped[str] = mapped_column(String(128), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
