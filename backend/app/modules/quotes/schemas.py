from pydantic import BaseModel


class FyersConfigIn(BaseModel):
    app_id: str = ""
    app_secret: str = ""
    pin: str = ""
    redirect_uri: str = ""
    client_id: str = ""
    totp_key: str = ""


class FyersConfigOut(BaseModel):
    configured: bool
    app_saved: bool
    connected: bool
    app_id: str = ""
    client_id: str = ""
    totp_saved: bool = False
    refresh_until: str | None = None
    detail: str


class FyersConnectOut(BaseModel):
    url: str
