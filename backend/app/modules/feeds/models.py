import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class SourceFeed(Base, TimestampMixin):
    """How one source channel is read.

    `options` holds non-secret settings for `kind`. A Telegram channel id belongs
    here. `api_id`, `api_hash`, session files, and API secrets do not.
    """

    __tablename__ = "source_feeds"
    __table_args__ = (
        CheckConstraint("kind IN ('none', 'telegram', 'http_api')", name="kind"),
        CheckConstraint("status IN ('active', 'inactive')", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_channels.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    options: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    history_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
