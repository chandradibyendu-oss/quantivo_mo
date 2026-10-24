from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import CorrelationId, Db, Principal, require_permission
from app.modules.brokers.schemas import BrokerConnectionOut
from app.modules.brokers.service import connect_simulated, disconnect_simulated, list_connections

router = APIRouter(prefix="/api/v1", tags=["brokers"])
Connector = Annotated[Principal, Depends(require_permission("broker.connect"))]


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


@router.post("/broker/connections/simulated", response_model=BrokerConnectionOut)
def connect(principal: Connector, db: Db, correlation_id: CorrelationId) -> BrokerConnectionOut:
    return _out(connect_simulated(db, principal.user.id, correlation_id=correlation_id))


@router.post("/broker/connections/simulated/disconnect", response_model=BrokerConnectionOut)
def disconnect(principal: Connector, db: Db, correlation_id: CorrelationId) -> BrokerConnectionOut:
    return _out(disconnect_simulated(db, principal.user.id, correlation_id=correlation_id))
