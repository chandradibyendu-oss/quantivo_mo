from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.core.deps import CorrelationId, Db, Principal, require_permission
from app.core.errors import AppError
from app.modules.audit.service import record
from app.modules.quotes.credentials import clear_fyers_credentials, save_fyers_app
from app.modules.quotes.schemas import FyersConfigIn, FyersConfigOut, FyersConnectOut
from app.modules.quotes.session import begin_login, complete_login, fyers_status

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
Reader = Annotated[Principal, Depends(require_permission("admin.feeds.read"))]
Writer = Annotated[Principal, Depends(require_permission("admin.feeds.write"))]

_CONNECTED = """<!DOCTYPE html>
<html><body><p>Fyers is connected. Close this window and return to Admin.</p></body></html>
"""
_FAILED = """<!DOCTYPE html>
<html><body><p>Fyers did not connect. Return to Admin and sign in again.</p></body></html>
"""


def _status() -> FyersConfigOut:
    current = fyers_status()
    return FyersConfigOut(
        configured=current.configured,
        app_saved=current.app_saved,
        connected=current.connected,
        refresh_until=current.refresh_until,
        detail=current.detail,
    )


@router.get("/fyers", response_model=FyersConfigOut)
def read_fyers(principal: Reader) -> FyersConfigOut:
    del principal
    return _status()


@router.put("/fyers", response_model=FyersConfigOut)
def update_fyers(
    body: FyersConfigIn,
    principal: Writer,
    db: Db,
    correlation_id: CorrelationId,
) -> FyersConfigOut:
    save_fyers_app(body.app_id, body.app_secret, body.pin, body.redirect_uri)
    record(
        db,
        action="quotes.fyers_saved",
        entity_type="quote_feed",
        entity_id=None,
        payload={"app_saved": True},
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )
    return _status()


@router.post("/fyers/connect", response_model=FyersConnectOut)
def connect_fyers(principal: Writer) -> FyersConnectOut:
    return FyersConnectOut(url=begin_login(str(principal.user.id)))


@router.get("/fyers/callback", response_class=HTMLResponse)
def fyers_callback(
    db: Db,
    correlation_id: CorrelationId,
    auth_code: str = "",
    state: str = "",
) -> HTMLResponse:
    try:
        user_id, refresh_end = complete_login(state, auth_code)
    except AppError:
        return HTMLResponse(_FAILED, status_code=400)
    record(
        db,
        action="quotes.fyers_connected",
        entity_type="quote_feed",
        entity_id=None,
        payload={"connected": True, "refresh_until": refresh_end.date().isoformat()},
        actor_user_id=UUID(user_id),
        correlation_id=correlation_id,
    )
    return HTMLResponse(_CONNECTED)


@router.delete("/fyers", response_model=FyersConfigOut)
def remove_fyers(
    principal: Writer,
    db: Db,
    correlation_id: CorrelationId,
) -> FyersConfigOut:
    clear_fyers_credentials()
    record(
        db,
        action="quotes.fyers_cleared",
        entity_type="quote_feed",
        entity_id=None,
        payload={"configured": False},
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )
    return _status()
