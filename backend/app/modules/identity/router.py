from typing import Annotated

from fastapi import APIRouter, Depends, Header

from app.core.deps import CorrelationId, CurrentPrincipal, Db, Principal, require_permission
from app.modules.identity import service
from app.modules.identity.schemas import (
    MeOut,
    OtpRequestIn,
    OtpRequestOut,
    OtpVerifyIn,
    ProfileUpdate,
    RefreshIn,
    TokenOut,
)

router = APIRouter(prefix="/api/v1", tags=["identity"])
ProfileReader = Annotated[Principal, Depends(require_permission("profile.read"))]
ProfileWriter = Annotated[Principal, Depends(require_permission("profile.write"))]


@router.post("/auth/otp/request", response_model=OtpRequestOut)
def request_otp(body: OtpRequestIn, db: Db, correlation_id: CorrelationId) -> OtpRequestOut:
    return service.request_otp(db, body.phone, correlation_id=correlation_id)


@router.post("/auth/otp/verify", response_model=TokenOut)
def verify_otp(
    body: OtpVerifyIn,
    db: Db,
    correlation_id: CorrelationId,
    user_agent: Annotated[str | None, Header()] = None,
) -> TokenOut:
    return service.verify_otp(
        db,
        phone_raw=body.phone,
        challenge_id=body.challenge_id,
        otp=body.otp,
        device_label=body.device_label,
        user_agent=user_agent,
        correlation_id=correlation_id,
    )


@router.post("/auth/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Db, correlation_id: CorrelationId) -> TokenOut:
    return service.refresh_session(db, body.refresh_token, correlation_id=correlation_id)


@router.post("/auth/logout", status_code=204)
def logout(principal: CurrentPrincipal, db: Db, correlation_id: CorrelationId) -> None:
    service.logout(db, principal, correlation_id=correlation_id)


@router.get("/me", response_model=MeOut)
def me(principal: ProfileReader) -> MeOut:
    return service.to_me(principal)


@router.put("/me", response_model=MeOut)
def update_me(
    body: ProfileUpdate,
    db: Db,
    correlation_id: CorrelationId,
    principal: ProfileWriter,
) -> MeOut:
    return service.update_profile(db, principal, body, correlation_id=correlation_id)
