from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.money import money
from app.modules.audit.service import record
from app.modules.risk.models import RiskProfile
from app.modules.risk.schemas import RiskProfileOut, RiskProfileUpdate


def get_profile(db: Session, user_id: UUID) -> RiskProfile:
    profile = db.scalar(select(RiskProfile).where(RiskProfile.user_id == user_id))
    if profile is None:
        raise AppError(409, "risk_profile_missing", "Set a risk profile before calculating quantity.")
    return profile


def to_out(profile: RiskProfile) -> RiskProfileOut:
    return RiskProfileOut(
        capital_allocation_inr=money(profile.capital_allocation_inr) or "0.00",
        max_risk_inr=money(profile.max_risk_inr) or "0.00",
        max_quantity=profile.max_quantity,
        max_exposure_inr=money(profile.max_exposure_inr),
        allowed_products=list(profile.allowed_products),
    )


def update_profile(
    db: Session,
    *,
    user_id: UUID,
    body: RiskProfileUpdate,
    correlation_id: str | None,
) -> RiskProfile:
    profile = get_profile(db, user_id)
    profile.capital_allocation_inr = body.capital_allocation_inr.quantize(Decimal("0.01"))
    profile.max_risk_inr = body.max_risk_inr.quantize(Decimal("0.01"))
    profile.max_quantity = body.max_quantity
    profile.max_exposure_inr = (
        None if body.max_exposure_inr is None else body.max_exposure_inr.quantize(Decimal("0.01"))
    )
    profile.allowed_products = list(body.allowed_products)
    record(
        db,
        action="risk_profile.updated",
        entity_type="risk_profile",
        entity_id=profile.id,
        payload={
            "capital_allocation_inr": money(profile.capital_allocation_inr),
            "max_risk_inr": money(profile.max_risk_inr),
            "max_quantity": profile.max_quantity,
            "allowed_products": profile.allowed_products,
        },
        actor_user_id=user_id,
        correlation_id=correlation_id,
    )
    db.commit()
    return profile
