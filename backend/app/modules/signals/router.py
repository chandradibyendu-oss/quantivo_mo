from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.deps import CorrelationId, Db, Principal, require_permission
from app.modules.scanners.service import sync_mock_feed
from app.modules.signals.schemas import MockFeedSyncOut, SignalChartOut, SignalDetail, SignalListOut
from app.modules.signals.views import get_chart, get_signal, list_signals

router = APIRouter(prefix="/api/v1", tags=["signals"])
Reader = Annotated[Principal, Depends(require_permission("signals.read"))]


@router.get("/signals", response_model=SignalListOut)
def signals(
    principal: Reader,
    db: Db,
    scanner_id: UUID | None = None,
    channel_id: UUID | None = None,
    view: Literal["actionable", "all"] = "actionable",
) -> SignalListOut:
    return list_signals(
        db,
        user_id=principal.user.id,
        scanner_id=scanner_id,
        view=view,
        channel_id=channel_id,
    )


@router.get("/signals/{signal_id}", response_model=SignalDetail)
def signal_detail(signal_id: UUID, principal: Reader, db: Db) -> SignalDetail:
    return get_signal(db, user_id=principal.user.id, signal_id=signal_id)


@router.get("/signals/{signal_id}/chart", response_model=SignalChartOut)
def signal_chart(
    signal_id: UUID,
    principal: Reader,
    db: Db,
    interval: Literal["1m", "5m"] = "5m",
) -> SignalChartOut:
    return get_chart(db, user_id=principal.user.id, signal_id=signal_id, interval=interval)


@router.post("/dev/mock-feed/sync", response_model=MockFeedSyncOut)
def mock_feed_sync(principal: Reader, db: Db, correlation_id: CorrelationId) -> MockFeedSyncOut:
    return sync_mock_feed(db, correlation_id=correlation_id)
