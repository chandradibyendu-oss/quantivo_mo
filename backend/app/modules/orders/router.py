from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import CorrelationId, Db, Principal, require_permission
from app.core.errors import AppError
from app.modules.orders.service import refuse_order
from app.modules.signals.schemas import OrderRequest

router = APIRouter(prefix="/api/v1", tags=["orders"])
Trader = Annotated[Principal, Depends(require_permission("orders.create"))]


@router.post("/orders", status_code=403)
def create_order(body: OrderRequest, principal: Trader, db: Db, correlation_id: CorrelationId) -> None:
    refuse_order(db, principal, body, correlation_id=correlation_id)
    raise AppError(
        403,
        "trading_disabled",
        "Order placement is disabled. The simulated broker can record a connection, but it does not accept, fill, or protect orders.",
    )
