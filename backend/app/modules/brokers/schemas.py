from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class KiteAppIn(BaseModel):
    api_key: str = ""
    api_secret: str = ""
    redirect_uri: str = ""


class KiteAppOut(BaseModel):
    app_saved: bool
    detail: str


class KiteAccountOut(BaseModel):
    app_saved: bool
    status: str
    client_id: str | None
    detail: str


class KiteConnectOut(BaseModel):
    url: str


class BrokerConnectionOut(BaseModel):
    id: UUID
    broker_code: str
    status: str
    display_name: str | None
    external_account_ref: str | None
    last_authenticated_at: datetime | None
    status_message: str | None
    stores_credentials: Literal[False] = False
    order_placement: Literal["disabled"] = "disabled"
