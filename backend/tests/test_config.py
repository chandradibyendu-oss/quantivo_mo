import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(**overrides):
    values = {
        "environment": "development",
        "database_url": "postgresql+psycopg://quantivo:quantivo@localhost:5433/quantivo",
        "secret_key": "x" * 40,
        "auth_provider": "dev_mock",
        "live_trading_enabled": False,
        "dev_activation_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_production_rejects_the_development_otp_provider():
    with pytest.raises(ValidationError, match="dev_mock"):
        _settings(environment="production", dev_activation_enabled=False)


def test_live_trading_cannot_be_enabled():
    with pytest.raises(ValidationError, match="LIVE_TRADING_ENABLED"):
        _settings(live_trading_enabled=True)


def test_short_secret_is_rejected():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _settings(secret_key="too-short")
