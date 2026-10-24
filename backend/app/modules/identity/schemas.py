from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class OtpRequestIn(BaseModel):
    phone: str = Field(min_length=1, max_length=20)


class OtpRequestOut(BaseModel):
    challenge_id: UUID
    expires_in_seconds: int
    delivery: Literal["dev_mock"]
    dev_otp: str | None = None


class OtpVerifyIn(BaseModel):
    phone: str = Field(min_length=1, max_length=20)
    challenge_id: UUID
    otp: str = Field(pattern=r"^\d{6}$")
    device_label: str | None = Field(default=None, max_length=120)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_seconds: int
    user_id: UUID


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=512)


class MeOut(BaseModel):
    id: UUID
    phone_e164: str
    display_name: str | None
    status: str
    roles: list[str]


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
