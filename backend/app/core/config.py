from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-specific configuration. Production startup is refused until a real OTP provider exists."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str
    secret_key: str
    auth_provider: Literal["dev_mock"] = "dev_mock"
    live_trading_enabled: bool = False
    dev_activation_enabled: bool = True
    cors_origins: str = ""
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    otp_ttl_seconds: int = 300
    otp_request_limit: int = 5
    otp_request_window_seconds: int = 900
    otp_max_attempts: int = 5
    log_level: str = "INFO"
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    telegram_session_path: str = ""
    fyers_app_id: str = ""
    fyers_app_secret: str = ""
    fyers_pin: str = ""
    fyers_access_token: str = ""
    fyers_refresh_token: str = ""
    fyers_access_until: str = ""
    fyers_refresh_until: str = ""
    fyers_redirect_uri: str = ""

    @field_validator("secret_key")
    @classmethod
    def secret_key_must_be_long_enough(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters.")
        return value

    @model_validator(mode="after")
    def enforce_safe_defaults(self) -> "Settings":
        if self.environment == "production" and self.auth_provider == "dev_mock":
            raise ValueError(
                "AUTH_PROVIDER=dev_mock cannot be used when ENVIRONMENT=production. "
                "Configure a real OTP provider before production startup."
            )
        if self.live_trading_enabled:
            raise ValueError(
                "LIVE_TRADING_ENABLED must stay false until a reviewed broker integration exists."
            )
        if self.environment == "production" and self.dev_activation_enabled:
            raise ValueError("Development scanner activation cannot be enabled in production.")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def expose_dev_otp(self) -> bool:
        return self.auth_provider == "dev_mock" and self.environment in {"development", "test"}

    @property
    def fyers_quotes_configured(self) -> bool:
        return bool(self.fyers_app_id.strip() and self.fyers_access_token.strip())

    @property
    def telegram_login_configured(self) -> bool:
        path = self.telegram_session_path.strip()
        return bool(
            self.telegram_api_id.strip().isdigit()
            and self.telegram_api_hash.strip()
            and path
            and Path(f"{path}.session").is_file()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
