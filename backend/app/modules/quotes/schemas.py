from pydantic import BaseModel


class FyersConfigIn(BaseModel):
    app_id: str = ""
    app_secret: str = ""
    pin: str = ""
    redirect_uri: str = ""


class FyersConfigOut(BaseModel):
    configured: bool
    app_saved: bool
    connected: bool
    refresh_until: str | None = None
    detail: str


class FyersConnectOut(BaseModel):
    url: str
