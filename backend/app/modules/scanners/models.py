import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class ScannerProvider(Base, TimestampMixin):
    __tablename__ = "scanner_providers"
    __table_args__ = (CheckConstraint("status IN ('active', 'inactive')", name="status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    monogram: Mapped[str] = mapped_column(String(4), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class Scanner(Base, TimestampMixin):
    __tablename__ = "scanners"
    __table_args__ = (
        UniqueConstraint("provider_id", "code", name="uq_scanners_provider_code"),
        CheckConstraint("status IN ('active', 'inactive')", name="status"),
        CheckConstraint(
            "billing_frequency IS NULL OR billing_frequency IN ('monthly', 'quarterly', 'annual')",
            name="billing_frequency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scanner_providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    price_inr: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    billing_frequency: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class SourceChannel(Base, TimestampMixin):
    """One source inside a scanner, such as Mani's Equity channel.

    Horizon alias rules belong to this row and are not applied to another channel.
    Phase 1 seeds one channel and does not register users per channel.
    """

    __tablename__ = "source_channels"
    __table_args__ = (
        UniqueConstraint("scanner_id", "code", name="uq_source_channels_scanner_code"),
        CheckConstraint("segment IN ('equity', 'fno', 'commodity')", name="segment"),
        CheckConstraint("status IN ('active', 'inactive')", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scanner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scanners.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    horizon_aliases: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class ChannelRegistration(Base, TimestampMixin):
    """A trader's grant for one source channel. Scanner activation does not write this row."""

    __tablename__ = "channel_registrations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_channel_id",
            name="uq_channel_registrations_user_channel",
        ),
        CheckConstraint("status IN ('active', 'inactive')", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
