import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_ROOT)
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "postgresql+psycopg://quantivo:quantivo@localhost:5433/quantivo_test"
os.environ["SECRET_KEY"] = "test-only-secret-key-not-for-production-00"
os.environ["AUTH_PROVIDER"] = "dev_mock"
os.environ["LIVE_TRADING_ENABLED"] = "false"
os.environ["DEV_ACTIVATION_ENABLED"] = "true"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["CORS_ORIGINS"] = ""
os.environ["TELEGRAM_API_ID"] = ""
os.environ["TELEGRAM_API_HASH"] = ""
os.environ["TELEGRAM_SESSION_PATH"] = ""
os.environ["NSE_EQUITY_DIRECTORY"] = "off"

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import get_engine, get_session_factory
from app.main import app
from app.seed import seed_reference_data

get_settings.cache_clear()
get_engine.cache_clear()
get_session_factory.cache_clear()


def _ensure_test_database() -> None:
    with psycopg.connect("postgresql://quantivo:quantivo@localhost:5433/quantivo", autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = 'quantivo_test'").fetchone()
        if exists is None:
            conn.execute("CREATE DATABASE quantivo_test OWNER quantivo")


@pytest.fixture(scope="session")
def engine():
    _ensure_test_database()
    command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    migrated = get_engine()
    yield migrated
    migrated.dispose()


def _truncate(migrated) -> None:
    with migrated.begin() as connection:
        names = [
            row[0]
            for row in connection.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            )
        ]
        if names:
            quoted = ", ".join(f'"{name}"' for name in names)
            connection.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db(engine):
    _truncate(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    seed_reference_data(session)
    session.commit()
    yield session
    session.close()


@pytest.fixture
def client(db):
    with TestClient(app) as test_client:
        yield test_client
