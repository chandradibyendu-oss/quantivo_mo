from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.deps import CorrelationId, Db, Principal, require_permission
from app.modules.orders.schemas import AdminOrderOut, OrderBookOut, OrderIntentOut, OrderPreviewOut
from app.modules.orders.service import (
    confirm_order,
    delete_proposed_order,
    list_admin_orders,
    list_orders,
    open_order,
    preview_order,
)
from app.modules.signals.schemas import OrderPreviewIn, OrderRequest

router = APIRouter(prefix="/api/v1", tags=["orders"])
Trader = Annotated[Principal, Depends(require_permission("orders.create"))]
Operator = Annotated[Principal, Depends(require_permission("admin.feeds.write"))]


@router.post("/orders/preview", response_model=OrderPreviewOut)
def preview(body: OrderPreviewIn, principal: Trader, db: Db) -> OrderPreviewOut:
    return preview_order(db, principal, body)


@router.get("/orders", response_model=list[OrderBookOut])
def read_orders(principal: Trader, db: Db) -> list[OrderBookOut]:
    return list_orders(db, principal)


@router.get("/orders/open", response_model=OrderIntentOut)
def read_open_order(signal_id: UUID, principal: Trader, db: Db) -> OrderIntentOut:
    return open_order(db, principal, signal_id)


@router.get("/admin/orders", response_model=list[AdminOrderOut])
def read_admin_orders(principal: Operator, db: Db) -> list[AdminOrderOut]:
    del principal
    return list_admin_orders(db)


@router.delete("/admin/orders/{order_id}", status_code=204)
def remove_admin_order(
    order_id: UUID,
    principal: Operator,
    db: Db,
    correlation_id: CorrelationId,
) -> None:
    delete_proposed_order(
        db,
        order_id=order_id,
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )


@router.post("/orders", response_model=OrderIntentOut)
def create_order(
    body: OrderRequest,
    principal: Trader,
    db: Db,
    correlation_id: CorrelationId,
) -> OrderIntentOut:
    return confirm_order(db, principal, body, correlation_id=correlation_id)
