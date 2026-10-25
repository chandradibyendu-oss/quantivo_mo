from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class TargetOut(BaseModel):
    label: str
    price: str
    risk_reward: str | None = None


class ProviderValues(BaseModel):
    source: Literal["provider"] = "provider"
    trigger_price: str
    stop_loss: str
    targets: list[TargetOut]
    note: str | None


class QuantivoValues(BaseModel):
    source: Literal["quantivo"] = "quantivo"
    suggested_quantity: int | None
    per_share_risk: str | None
    estimated_risk_inr: str | None
    notional_inr: str | None
    capital_allocation_inr: str
    max_risk_inr: str
    formula: str
    funds_check: str
    unavailable_reason: str | None


class CallClocksOut(BaseModel):
    intraday_btst_minutes: int
    short_term_days: int
    long_term_days: int


class CallClocksIn(BaseModel):
    intraday_btst_minutes: int = Field(ge=1, le=1440)
    short_term_days: int = Field(ge=1, le=365)
    long_term_days: int = Field(ge=1, le=365)


class SignalCard(BaseModel):
    id: UUID
    symbol: str
    exchange: str
    side: str
    timeframe: str
    product_hint: str
    status: str
    stored_status: str
    warning: str | None
    executable: bool
    guide: Literal[
        "waiting",
        "window_over",
        "checking",
        "caution",
        "not_valid",
        "entry",
        "t1_trail",
        "t2_trail",
        "trail",
        "final",
        "stop",
        "stale",
        "expired",
        "no_symbol",
    ]
    guide_label: str
    guide_hint: str
    published_at: datetime
    expires_at: datetime
    provider_name: str
    scanner_id: UUID
    scanner_name: str
    segment: str
    channel_code: str
    channel_name: str
    horizon_raw: str
    lot_size: int
    provider_values: ProviderValues
    quantivo_values: QuantivoValues
    suggested_quantity: int | None
    last_price: str | None = None
    change_percent: str | None = None
    quote_label: Literal["LTP", "Last LTP"] = "Last LTP"
    quote_state: Literal["ready", "missing", "unconfigured", "unavailable"] = "unconfigured"


class CandleOut(BaseModel):
    time: str
    open: str
    high: str
    low: str
    close: str


class SignalChartOut(BaseModel):
    symbol: str
    side: str
    interval: Literal["1m", "5m"]
    session_date: str
    quote_label: Literal["LTP", "Last LTP"]
    last_price: str | None
    change_percent: str | None = None
    quote_state: Literal["ready", "checking", "missing", "unconfigured", "unavailable"]
    trigger_price: str
    stop_loss: str
    targets: list[TargetOut]
    candles: list[CandleOut]


class BrokerSummary(BaseModel):
    code: str
    status: str
    last_authenticated_at: datetime | None
    order_placement: Literal["disabled"] = "disabled"
    message: str


class SignalDetail(SignalCard):
    broker: BrokerSummary


class SignalListOut(BaseModel):
    entitled: bool
    scanner_id: UUID | None
    scanner_name: str | None
    provider_name: str | None
    provider_monogram: str | None
    feed_mode: Literal["mock", "telegram", "telegram_pending"] = "mock"
    feed_connection: Literal["mock_seed", "telegram", "telegram_pending"] = "mock_seed"
    as_of: datetime | None
    broker_status: str
    hidden_non_actionable: int
    omitted_channels: list[str] = []
    registration_required: bool = False
    selected_channel_name: str | None = None
    quote_feed: Literal["fyers", "unconfigured", "unavailable"] = "unconfigured"
    signals: list[SignalCard]


class MockFeedSyncOut(BaseModel):
    created: int
    unchanged: int
    revised: int


class OrderTargetIn(BaseModel):
    label: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,15}$")
    price: str = Field(pattern=r"^(?:0|[1-9]\d{0,9})(?:\.\d{1,4})?$")


class OrderRequest(BaseModel):
    signal_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_:\-]+$")
    product: Literal["MIS", "CNC"]
    quantity: int = Field(gt=0, le=1_000_000)
    side: Literal["BUY", "SELL"] | None = None
    trigger_price: str | None = Field(default=None, pattern=r"^(?:0|[1-9]\d{0,9})(?:\.\d{1,4})?$")
    stop_loss: str | None = Field(default=None, pattern=r"^(?:0|[1-9]\d{0,9})(?:\.\d{1,4})?$")
    targets: list[OrderTargetIn] | None = Field(default=None, min_length=1, max_length=4)

    @model_validator(mode="after")
    def trigger_and_stop_together(self) -> "OrderRequest":
        if (self.trigger_price is None) != (self.stop_loss is None):
            raise ValueError("Enter both the trigger and the stop.")
        return self


class OrderPreviewIn(BaseModel):
    signal_id: UUID
    side: Literal["BUY", "SELL"]
    product: Literal["MIS", "CNC"]
    trigger_price: str = Field(pattern=r"^(?:0|[1-9]\d{0,9})(?:\.\d{1,4})?$")
    stop_loss: str = Field(pattern=r"^(?:0|[1-9]\d{0,9})(?:\.\d{1,4})?$")
    targets: list[OrderTargetIn] = Field(min_length=1, max_length=4)
