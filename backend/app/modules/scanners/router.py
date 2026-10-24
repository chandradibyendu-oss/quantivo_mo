from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.deps import CorrelationId, Db, Principal, require_permission
from app.core.errors import AppError
from app.modules.scanners.channels import set_registration, trader_channels
from app.modules.scanners.models import SourceChannel
from app.modules.scanners.schemas import ActivationOut, RegistrationIn, ScannerOut, TraderChannelOut
from app.modules.scanners.service import list_catalogue
from app.modules.subscriptions.service import (
    activate_for_development,
    entitled_scanner_ids,
    is_entitled,
)

router = APIRouter(prefix="/api/v1", tags=["scanners"])
Reader = Annotated[Principal, Depends(require_permission("scanners.read"))]
Activator = Annotated[Principal, Depends(require_permission("subscriptions.activate"))]


@router.get("/scanners", response_model=list[ScannerOut])
def scanners(principal: Reader, db: Db) -> list[ScannerOut]:
    return list_catalogue(db, principal.user.id)


def _channel_out(channel: SourceChannel, registered: bool) -> TraderChannelOut:
    return TraderChannelOut(
        id=channel.id,
        scanner_id=channel.scanner_id,
        name=channel.name,
        segment=channel.segment,
        registered=registered,
    )


@router.get("/source-channels", response_model=list[TraderChannelOut])
def source_channels(
    principal: Reader, db: Db, scanner_id: UUID | None = None
) -> list[TraderChannelOut]:
    entitled = entitled_scanner_ids(db, principal.user.id)
    if not entitled:
        raise AppError(
            403,
            "entitlement_required",
            "Activate this scanner before reading its channels.",
        )
    if scanner_id is not None and scanner_id not in entitled:
        raise AppError(
            403,
            "entitlement_required",
            "Activate this scanner before reading its channels.",
        )
    chosen = [scanner_id] if scanner_id is not None else entitled
    rows: list[TraderChannelOut] = []
    for chosen_id in chosen:
        rows.extend(
            _channel_out(channel, registered)
            for channel, registered in trader_channels(
                db, user_id=principal.user.id, scanner_id=chosen_id
            )
        )
    return rows


@router.put("/source-channels/{channel_id}/registration", response_model=TraderChannelOut)
def registration(
    channel_id: UUID,
    body: RegistrationIn,
    principal: Reader,
    db: Db,
    correlation_id: CorrelationId,
) -> TraderChannelOut:
    channel = db.get(SourceChannel, channel_id)
    entitled = channel is not None and channel.status == "active"
    if entitled and not is_entitled(db, principal.user.id, channel.scanner_id):
        entitled = False
    if not entitled or channel is None:
        raise AppError(404, "channel_not_found", "That source channel is not in the catalogue.")
    saved = set_registration(
        db,
        user_id=principal.user.id,
        scanner_id=channel.scanner_id,
        channel_id=channel_id,
        active=body.active,
        correlation_id=correlation_id,
    )
    return _channel_out(saved, body.active)


@router.post("/scanners/{scanner_id}/activate", response_model=ActivationOut)
def activate(
    scanner_id: UUID,
    principal: Activator,
    db: Db,
    correlation_id: CorrelationId,
) -> ActivationOut:
    subscription, entitlement = activate_for_development(
        db,
        user_id=principal.user.id,
        scanner_id=scanner_id,
        correlation_id=correlation_id,
    )
    return ActivationOut(
        subscription_id=subscription.id,
        entitlement_id=entitlement.id,
        status=subscription.status,
        activation_method=subscription.activation_method,
        payment_status=None,
    )
