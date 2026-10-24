from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.errors import AppError
from app.modules.audit.service import record
from app.modules.scanners.models import SourceChannel
from app.modules.signals.models import Signal
from app.modules.signals.normalization import NormalizedSignal, content_hash, target_payload


class IngestOutcome(str, Enum):
    CREATED = "created"
    UNCHANGED = "unchanged"
    REVISED = "revised"


def ingest(
    db: Session,
    *,
    scanner_id,
    draft: NormalizedSignal,
    correlation_id: str | None,
) -> IngestOutcome:
    channel = db.scalar(
        select(SourceChannel).where(
            SourceChannel.scanner_id == scanner_id,
            SourceChannel.code == draft.channel_code,
            SourceChannel.status == "active",
        )
    )
    if channel is None:
        raise AppError(
            409,
            "channel_not_seeded",
            "That source channel is not in the catalogue. Run python -m app.seed.",
        )
    if draft.segment != channel.segment:
        raise AppError(
            409,
            "segment_mismatch",
            "The call's segment does not match its source channel.",
        )

    digest = content_hash(draft)
    existing = db.scalar(
        select(Signal).where(
            Signal.scanner_id == scanner_id,
            Signal.external_ref == draft.external_ref,
        )
    )
    if existing is not None and existing.content_hash == digest:
        return IngestOutcome.UNCHANGED

    fields = {
        "source_channel_id": channel.id,
        "segment": channel.segment,
        "horizon_raw": draft.horizon_raw,
        "symbol": draft.symbol,
        "exchange": draft.exchange,
        "side": draft.side,
        "timeframe": draft.timeframe,
        "product_hint": draft.product_hint,
        "trigger_price": draft.trigger_price,
        "stop_loss": draft.stop_loss,
        "targets": target_payload(draft.targets),
        "provider_note": draft.provider_note,
        "status": draft.status,
        "expires_at": draft.expires_at,
        "content_hash": digest,
        "lot_size": draft.lot_size,
        "match_status": draft.match_status,
        "origin": draft.origin,
    }
    if existing is None:
        signal = Signal(scanner_id=scanner_id, external_ref=draft.external_ref, published_at=draft.published_at, **fields)
        db.add(signal)
        db.flush()
        record(
            db,
            action="signal.ingested",
            entity_type="signal",
            entity_id=signal.id,
            payload={"external_ref": draft.external_ref, "symbol": draft.symbol, "status": draft.status},
            correlation_id=correlation_id,
        )
        return IngestOutcome.CREATED

    for name, value in fields.items():
        setattr(existing, name, value)
    existing.updated_at = utcnow()
    record(
        db,
        action="signal.revised",
        entity_type="signal",
        entity_id=existing.id,
        payload={"external_ref": draft.external_ref, "symbol": draft.symbol, "status": draft.status},
        correlation_id=correlation_id,
    )
    return IngestOutcome.REVISED
