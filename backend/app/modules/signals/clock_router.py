from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import CorrelationId, Db, Principal, require_permission
from app.modules.audit.service import record
from app.modules.signals.clocks import CallClocks, load_clocks, save_clocks
from app.modules.signals.schemas import CallClocksIn, CallClocksOut

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
Reader = Annotated[Principal, Depends(require_permission("admin.feeds.read"))]
Writer = Annotated[Principal, Depends(require_permission("admin.feeds.write"))]


def _out(clocks: CallClocks) -> CallClocksOut:
    return CallClocksOut(
        intraday_btst_minutes=clocks.intraday_minutes,
        short_term_days=clocks.short_term_days,
        long_term_days=clocks.long_term_days,
    )


@router.get("/call-clocks", response_model=CallClocksOut)
def read_call_clocks(principal: Reader, db: Db) -> CallClocksOut:
    del principal
    return _out(load_clocks(db))


@router.put("/call-clocks", response_model=CallClocksOut)
def update_call_clocks(
    body: CallClocksIn,
    principal: Writer,
    db: Db,
    correlation_id: CorrelationId,
) -> CallClocksOut:
    clocks = save_clocks(
        db,
        CallClocks(body.intraday_btst_minutes, body.short_term_days, body.long_term_days),
    )
    record(
        db,
        action="signals.call_clocks_saved",
        entity_type="call_clock",
        entity_id=None,
        payload={
            "intraday_btst_minutes": clocks.intraday_minutes,
            "short_term_days": clocks.short_term_days,
            "long_term_days": clocks.long_term_days,
        },
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )
    return _out(clocks)
