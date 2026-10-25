from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.deps import CorrelationId, Db, Principal, require_permission
from app.modules.orders.schemas import OrderBookOut, OrderIntentOut, OrderPreviewOut
from app.modules.orders.service import confirm_order, list_orders, open_order, preview_order
from app.modules.signals.schemas import OrderPreviewIn, OrderRequest

router = APIRouter(prefix="/api/v1", tags=["orders"])
Trader = Annotated[Principal, Depends(require_permission("orders.create"))]


@router.post("/orders/preview", response_model=OrderPreviewOut)
def preview(body: OrderPreviewIn, principal: Trader, db: Db) -> OrderPreviewOut:
    return preview_order(db, principal, body)


@router.get("/orders", response_model=list[OrderBookOut])
def read_orders(principal: Trader, db: Db) -> list[OrderBookOut]:
    return list_orders(db, principal)


@router.get("/orders/open", response_model=OrderIntentOut)
def read_open_order(signal_id: UUID, principal: Trader, db: Db) -> OrderIntentOut:
    return open_order(db, principal, signal_id)


@router.post("/orders", response_model=OrderIntentOut)
def create_order(
    body: OrderRequest,
    principal: Trader,
    db: Db,
    correlation_id: CorrelationId,
) -> OrderIntentOut:
    return confirm_order(db, principal, body, correlation_id=correlation_id)
