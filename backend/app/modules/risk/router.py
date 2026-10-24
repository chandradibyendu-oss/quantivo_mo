from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import CorrelationId, Db, Principal, require_permission
from app.modules.risk.schemas import RiskProfileOut, RiskProfileUpdate
from app.modules.risk.service import get_profile, to_out, update_profile

router = APIRouter(prefix="/api/v1", tags=["risk"])
Reader = Annotated[Principal, Depends(require_permission("profile.read"))]
Writer = Annotated[Principal, Depends(require_permission("profile.write"))]


@router.get("/me/risk-profile", response_model=RiskProfileOut)
def read_risk_profile(principal: Reader, db: Db) -> RiskProfileOut:
    return to_out(get_profile(db, principal.user.id))


@router.put("/me/risk-profile", response_model=RiskProfileOut)
def write_risk_profile(
    body: RiskProfileUpdate,
    principal: Writer,
    db: Db,
    correlation_id: CorrelationId,
) -> RiskProfileOut:
    return to_out(
        update_profile(db, user_id=principal.user.id, body=body, correlation_id=correlation_id)
    )
