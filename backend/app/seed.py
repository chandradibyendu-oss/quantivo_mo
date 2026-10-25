"""Idempotent development catalogue and Mani's sample signal feed."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session_factory, utcnow
from app.core.logging import configure_logging
from app.modules.feeds.models import SourceFeed
from app.modules.identity.models import Permission, Role, RolePermission
from app.modules.scanners.mock_mani import (
    EQUITY_CHANNEL_CODE,
    PROVIDER_CODE,
    SCANNER_CODE,
    MockManiAdapter,
)
from app.modules.scanners.models import Scanner, ScannerProvider, SourceChannel
from app.modules.signals.service import ingest

PERMISSIONS = (
    ("profile.read", "Read the signed-in profile"),
    ("profile.write", "Update profile and risk preferences"),
    ("scanners.read", "Read the scanner catalogue"),
    ("subscriptions.activate", "Activate a development scanner entitlement"),
    ("signals.read", "Read entitled scanner signals"),
    ("broker.connect", "Sign in on Zerodha"),
    ("orders.create", "Submit an order request"),
    ("admin.users.read", "Read user accounts in a future admin portal"),
    ("admin.audit.read", "Read audit events in a future admin portal"),
    ("admin.feeds.read", "Read source-channel feed settings"),
    ("admin.feeds.write", "Update source-channel feed settings"),
)
USER_PERMISSIONS = tuple(code for code, _description in PERMISSIONS if not code.startswith("admin."))


def _permission(db: Session, code: str, description: str) -> Permission:
    row = db.scalar(select(Permission).where(Permission.code == code))
    if row is None:
        row = Permission(code=code, description=description)
        db.add(row)
        db.flush()
    else:
        row.description = description
    return row


def _role(db: Session, name: str, description: str, permission_ids: list) -> Role:
    row = db.scalar(select(Role).where(Role.name == name))
    if row is None:
        row = Role(name=name, description=description)
        db.add(row)
        db.flush()
    else:
        row.description = description
    for permission_id in permission_ids:
        exists = db.scalar(
            select(RolePermission).where(
                RolePermission.role_id == row.id,
                RolePermission.permission_id == permission_id,
            )
        )
        if exists is None:
            db.add(RolePermission(role_id=row.id, permission_id=permission_id))
    return row


def seed_reference_data(db: Session) -> Scanner:
    permissions = {code: _permission(db, code, description) for code, description in PERMISSIONS}
    _role(
        db,
        "user",
        "Standard signed-in user",
        [permissions[code].id for code in USER_PERMISSIONS],
    )
    _role(db, "admin", "Operator for a future admin portal", [row.id for row in permissions.values()])

    provider = db.scalar(select(ScannerProvider).where(ScannerProvider.code == PROVIDER_CODE))
    description = (
        "Mani's is the first scanner. Development sample calls stand in until the Telegram "
        "channel is connected. They are not market recommendations."
    )
    if provider is None:
        provider = ScannerProvider(
            code=PROVIDER_CODE,
            name="Mani's",
            monogram="M",
            description=description,
            status="active",
        )
        db.add(provider)
        db.flush()
    else:
        provider.name = "Mani's"
        provider.monogram = "M"
        provider.description = description
        provider.status = "active"

    scanner = db.scalar(
        select(Scanner).where(Scanner.provider_id == provider.id, Scanner.code == SCANNER_CODE)
    )
    scanner_description = "Mani's equity channel. Development sample calls stand in until Telegram is connected."
    if scanner is None:
        scanner = Scanner(
            provider_id=provider.id,
            code=SCANNER_CODE,
            name="Mani's Channel",
            description=scanner_description,
            category="Intraday",
            price_inr=Decimal("999.00"),
            billing_frequency="monthly",
            status="active",
        )
        db.add(scanner)
        db.flush()
    else:
        scanner.name = "Mani's Channel"
        scanner.description = scanner_description
        scanner.category = "Intraday"
        scanner.price_inr = Decimal("999.00")
        scanner.billing_frequency = "monthly"
        scanner.status = "active"

    channel = db.scalar(
        select(SourceChannel).where(
            SourceChannel.scanner_id == scanner.id,
            SourceChannel.code == EQUITY_CHANNEL_CODE,
        )
    )
    if channel is None:
        channel = SourceChannel(
            scanner_id=scanner.id,
            code=EQUITY_CHANNEL_CODE,
            name="Equity",
            segment="equity",
            horizon_aliases=[],
            status="active",
        )
        db.add(channel)
        db.flush()
    else:
        channel.name = "Equity"
        channel.segment = "equity"
        channel.status = "active"
    feed = db.scalar(select(SourceFeed).where(SourceFeed.source_channel_id == channel.id))
    if feed is None:
        db.add(
            SourceFeed(
                source_channel_id=channel.id,
                kind="none",
                status="active",
                options={},
            )
        )
        db.flush()
    return scanner


def seed_mock_signals(db: Session, scanner: Scanner) -> None:
    for draft in MockManiAdapter().fetch(utcnow()):
        ingest(db, scanner_id=scanner.id, draft=draft, correlation_id="seed")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    session = get_session_factory()()
    try:
        scanner = seed_reference_data(session)
        seed_mock_signals(session, scanner)
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    main()
