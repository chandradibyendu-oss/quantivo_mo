import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class NormalizedSignal:
    external_ref: str
    symbol: str
    exchange: str
    side: str
    timeframe: str
    product_hint: str
    trigger_price: Decimal
    stop_loss: Decimal
    targets: tuple[tuple[str, Decimal], ...]
    provider_note: str | None
    status: str
    published_at: datetime
    expires_at: datetime
    segment: str
    channel_code: str
    horizon_raw: str
    lot_size: int = 1
    match_status: str = "matched"
    origin: str = "sample"


def target_payload(targets: tuple[tuple[str, Decimal], ...]) -> list[dict[str, str]]:
    return [{"label": label, "price": format(price, "f")} for label, price in targets]


def content_hash(signal: NormalizedSignal) -> str:
    """Hash provider content. Timestamps are excluded so a repeat delivery stays stable."""

    payload = {
        "channel_code": signal.channel_code,
        "exchange": signal.exchange,
        "external_ref": signal.external_ref,
        "horizon_raw": signal.horizon_raw,
        "lot_size": signal.lot_size,
        "match_status": signal.match_status,
        "origin": signal.origin,
        "segment": signal.segment,
        "product_hint": signal.product_hint,
        "provider_note": signal.provider_note,
        "side": signal.side,
        "status": signal.status,
        "stop_loss": format(signal.stop_loss, "f"),
        "symbol": signal.symbol,
        "targets": target_payload(signal.targets),
        "timeframe": signal.timeframe,
        "trigger_price": format(signal.trigger_price, "f"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()
