import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class RiskProfile(Base, TimestampMixin):
    __tablename__ = "risk_profiles"
    __table_args__ = (
        CheckConstraint("capital_allocation_inr > 0", name="capital_positive"),
        CheckConstraint("max_risk_inr > 0", name="risk_positive"),
        CheckConstraint("max_risk_inr <= capital_allocation_inr", name="risk_within_capital"),
        CheckConstraint("max_quantity IS NULL OR max_quantity > 0", name="quantity_positive"),
        CheckConstraint("max_exposure_inr IS NULL OR max_exposure_inr > 0", name="exposure_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    capital_allocation_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    max_risk_inr: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    max_quantity: Mapped[int | None] = mapped_column(Integer)
    max_exposure_inr: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    allowed_products: Mapped[list] = mapped_column(JSONB, nullable=False)
