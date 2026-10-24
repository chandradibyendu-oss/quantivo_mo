from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ScannerOut(BaseModel):
    id: UUID
    provider_code: str
    provider_name: str
    monogram: str
    name: str
    description: str
    category: str
    price_inr: str | None
    billing_frequency: str | None
    entitlement_status: Literal["none", "active"]
    activation_method: str | None
    payment_status: str | None = None
    verified_rating: int | None = Field(
        default=None,
        description="Null until ratings come from a verified source.",
    )
    active_subscriber_count: int | None = Field(
        default=None,
        description="Null until the count comes from trustworthy data.",
    )


class TraderChannelOut(BaseModel):
    id: UUID
    scanner_id: UUID
    name: str
    segment: str
    registered: bool


class RegistrationIn(BaseModel):
    active: bool


class ActivationOut(BaseModel):
    subscription_id: UUID
    entitlement_id: UUID
    status: str
    activation_method: str
    payment_status: str | None = None
