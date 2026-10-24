from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


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
