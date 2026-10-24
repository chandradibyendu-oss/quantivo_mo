from sqlalchemy import text

from app.core.errors import AppError
from app.modules.audit.service import assert_payload_safe
from app.modules.brokers.adapter import OrderDraft
from app.modules.brokers.simulated import SimulatedBrokerAdapter
import pytest
from decimal import Decimal


ALLOWED_SENSITIVE_COLUMNS = {
    ("otp_challenges", "code_hash"),
    ("user_sessions", "refresh_token_hash"),
}
FRAGMENTS = ("password", "secret", "token", "otp", "credential", "api_key")


def test_tables_do_not_store_broker_or_auth_secrets(db):
    rows = db.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        )
    )
    offenders = []
    for table_name, column_name in rows:
        if (table_name, column_name) in ALLOWED_SENSITIVE_COLUMNS:
            continue
        lowered = column_name.lower()
        if any(fragment in lowered for fragment in FRAGMENTS):
            offenders.append(f"{table_name}.{column_name}")
    assert offenders == []


def test_required_lifecycle_tables_exist(db):
    rows = db.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    ).scalars()
    names = set(rows)
    expected = {
        "users",
        "user_sessions",
        "roles",
        "permissions",
        "broker_connections",
        "broker_accounts",
        "scanner_providers",
        "scanners",
        "scanner_subscriptions",
        "subscription_entitlements",
        "payment_transactions",
        "signals",
        "source_feeds",
        "risk_profiles",
        "order_intents",
        "broker_orders",
        "trade_executions",
        "position_snapshots",
        "notifications",
        "audit_events",
    }
    assert expected <= names


def test_audit_helper_rejects_sensitive_keys():
    with pytest.raises(AppError) as caught:
        assert_payload_safe({"refresh_token": "nope"})
    assert caught.value.code == "audit_rejected"


def test_simulated_adapter_cannot_place_an_order():
    adapter = SimulatedBrokerAdapter()
    draft = OrderDraft(
        symbol="RELIANCE",
        exchange="NSE",
        side="BUY",
        product="MIS",
        quantity=1,
        price=Decimal("2450.00"),
        idempotency_key="adapter-test",
    )
    with pytest.raises(Exception, match="does not place"):
        adapter.place_order(draft)
    assert adapter.get_positions() == []
    assert adapter.get_funds() is None
