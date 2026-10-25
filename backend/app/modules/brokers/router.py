from datetime import datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from app.core.deps import CorrelationId, Db, Principal, require_permission
from app.core.errors import AppError
from app.modules.audit.service import record
from app.modules.brokers.kite import (
    app_saved,
    begin_login,
    complete_login,
    disconnected_message,
    end_remote_session,
)
from app.modules.brokers.kite_store import clear_kite_app, save_kite_app
from app.modules.brokers.schemas import (
    BrokerConnectionOut,
    KiteAccountOut,
    KiteAppIn,
    KiteAppOut,
    KiteConnectOut,
)
from app.modules.brokers.service import (
    clear_zerodha_sessions,
    disconnect_zerodha,
    list_connections,
    record_zerodha,
    zerodha_account,
)

router = APIRouter(prefix="/api/v1", tags=["brokers"])
Connector = Annotated[Principal, Depends(require_permission("broker.connect"))]
Reader = Annotated[Principal, Depends(require_permission("admin.feeds.read"))]
Writer = Annotated[Principal, Depends(require_permission("admin.feeds.write"))]
IST = ZoneInfo("Asia/Kolkata")

_CONNECTED = """<!DOCTYPE html>
<html><body><p>Zerodha is connected. Close this window and return to Account.</p></body></html>
"""
_FAILED = """<!DOCTYPE html>
<html><body><p>Zerodha did not connect. Return to Account and sign in again.</p></body></html>
"""


def _out(connection) -> BrokerConnectionOut:
    return BrokerConnectionOut(
        id=connection.id,
        broker_code=connection.broker_code,
        status=connection.status,
        display_name=connection.display_name,
        external_account_ref=connection.external_account_ref,
        last_authenticated_at=connection.last_authenticated_at,
        status_message=connection.status_message,
    )


@router.get("/broker/connections", response_model=list[BrokerConnectionOut])
def connections(principal: Connector, db: Db) -> list[BrokerConnectionOut]:
    return [_out(connection) for connection in list_connections(db, principal.user.id)]


def _kite_out(account) -> KiteAccountOut:
    return KiteAccountOut(
        app_saved=account.app_saved,
        status=account.status,
        client_id=account.client_id,
        detail=account.detail,
    )


@router.get("/broker/zerodha", response_model=KiteAccountOut)
def read_zerodha(principal: Connector, db: Db) -> KiteAccountOut:
    return _kite_out(zerodha_account(db, principal.user.id, datetime.now(IST)))


@router.post("/broker/zerodha/connect", response_model=KiteConnectOut)
def connect_zerodha(principal: Connector) -> KiteConnectOut:
    return KiteConnectOut(url=begin_login(str(principal.user.id)))


@router.post("/broker/zerodha/disconnect", response_model=KiteAccountOut)
def disconnect_zerodha_route(
    principal: Connector,
    db: Db,
    correlation_id: CorrelationId,
) -> KiteAccountOut:
    end_remote_session(str(principal.user.id))
    disconnect_zerodha(db, principal.user.id, correlation_id=correlation_id)
    return _kite_out(zerodha_account(db, principal.user.id, datetime.now(IST)))


@router.get("/broker/zerodha/callback", response_class=HTMLResponse)
def zerodha_callback(
    db: Db,
    correlation_id: CorrelationId,
    request_token: str = "",
    status: str = "",
    state: str = "",
) -> HTMLResponse:
    try:
        done = complete_login(state, request_token, status)
        record_zerodha(
            db,
            UUID(done.quantivo_user_id),
            client_id=done.client_id,
            exchanges=done.exchanges,
            session_end=done.session_end,
            correlation_id=correlation_id,
        )
    except AppError:
        return HTMLResponse(_FAILED, status_code=400)
    return HTMLResponse(_CONNECTED)


@router.get("/admin/zerodha", response_model=KiteAppOut)
def read_kite_app(principal: Reader) -> KiteAppOut:
    del principal
    saved = app_saved()
    detail = (
        "The Kite app is saved. A trader signs in on Zerodha from Account. "
        "The session lasts until 6:00 AM IST and is not refreshed."
        if saved
        else "Save the Kite Connect api key and api secret. Register the callback URL on that app."
    )
    return KiteAppOut(app_saved=saved, detail=detail)


@router.put("/admin/zerodha", response_model=KiteAppOut)
def update_kite_app(
    body: KiteAppIn,
    principal: Writer,
    db: Db,
    correlation_id: CorrelationId,
) -> KiteAppOut:
    changed = save_kite_app(body.api_key, body.api_secret, body.redirect_uri)
    if changed:
        clear_zerodha_sessions(
            db,
            actor_user_id=principal.user.id,
            correlation_id=correlation_id,
            message=disconnected_message(),
        )
    record(
        db,
        action="broker.zerodha_app_saved",
        entity_type="broker_connection",
        entity_id=None,
        payload={"app_saved": True},
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )
    db.commit()
    return read_kite_app(principal)


@router.delete("/admin/zerodha", response_model=KiteAppOut)
def remove_kite_app(
    principal: Writer,
    db: Db,
    correlation_id: CorrelationId,
) -> KiteAppOut:
    clear_kite_app()
    clear_zerodha_sessions(db, actor_user_id=principal.user.id, correlation_id=correlation_id)
    return read_kite_app(principal)
