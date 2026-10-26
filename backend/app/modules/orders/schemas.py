from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.signals.schemas import TargetOut


class OrderPreviewOut(BaseModel):
    ok: bool
    quantity: int | None
    reason: str | None
    side: Literal["BUY", "SELL"]
    product: Literal["MIS", "CNC"]
    trigger_price: str
    stop_loss: str
    targets: list[TargetOut]


class OrderBookOut(BaseModel):
    id: UUID
    signal_id: UUID
    symbol: str
    exchange: str
    status: str
    side: Literal["BUY", "SELL"]
    product: Literal["MIS", "CNC"]
    quantity: int
    trigger_price: str
    stop_loss: str
    targets: list[TargetOut]
    sent_to_broker: Literal[False] = False
    protection: Literal["not_active"] = "not_active"
    saved_at: datetime
    message: str


class AdminOrderOut(BaseModel):
    id: UUID
    signal_id: UUID
    symbol: str
    side: Literal["BUY", "SELL"]
    product: Literal["MIS", "CNC"]
    quantity: int
    trigger_price: str
    stop_loss: str
    status: Literal["proposed"]
    phone_e164: str
    saved_at: datetime


class OrderIntentOut(BaseModel):
    id: UUID
    signal_id: UUID
    status: Literal["proposed"]
    side: Literal["BUY", "SELL"]
    product: Literal["MIS", "CNC"]
    quantity: int
    trigger_price: str
    stop_loss: str
    targets: list[TargetOut]
    sent_to_broker: Literal[False] = False
    protection: Literal["not_active"] = "not_active"
    message: str
