from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ScannerCreate(BaseModel):
    provider_name: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="Calls", max_length=64)


class ScannerCreated(BaseModel):
    id: UUID
    name: str
    provider_name: str


class ScannerRename(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    segment: Literal["equity", "fno", "commodity"]
    scanner_id: UUID | None = None


class ChannelRename(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class FeedUpdate(BaseModel):
    kind: Literal["none", "telegram", "http_api"]
    status: Literal["active", "inactive"] = "active"
    options: dict = Field(default_factory=dict)


class ReaderOut(BaseModel):
    state: Literal["sample", "login_not_configured", "login_present", "saved"]
    detail: str


class TelegramLoginOut(BaseModel):
    status: Literal["present", "missing"]
    detail: str


class ChannelLookupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ChannelMatchOut(BaseModel):
    channel_id: str
    title: str


class ChannelLookupOut(BaseModel):
    matches: list[ChannelMatchOut]


class FeedOut(BaseModel):
    channel_id: UUID
    scanner_id: UUID
    scanner_name: str
    channel_code: str
    channel_name: str
    segment: str
    kind: str
    status: str
    options: dict
    stored_calls: int = 0
    reader: ReaderOut
