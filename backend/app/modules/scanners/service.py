from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.errors import AppError
from app.core.money import money
from app.modules.feeds.service import scanner_feed_mode
from app.modules.scanners.mock_mani import SCANNER_CODE, MockManiAdapter
from app.modules.scanners.models import Scanner, ScannerProvider
from app.modules.scanners.schemas import ScannerOut
from app.modules.signals.schemas import MockFeedSyncOut
from app.modules.signals.service import ingest
from app.modules.subscriptions.service import entitlement_status


def list_catalogue(db: Session, user_id) -> list[ScannerOut]:
    rows = db.execute(
        select(Scanner, ScannerProvider)
        .join(ScannerProvider, Scanner.provider_id == ScannerProvider.id)
        .where(Scanner.status == "active", ScannerProvider.status == "active")
        .order_by(ScannerProvider.name, Scanner.name)
    ).all()
    catalogue: list[ScannerOut] = []
    for scanner, provider in rows:
        status, method = entitlement_status(db, user_id, scanner.id)
        catalogue.append(
            ScannerOut(
                id=scanner.id,
                provider_code=provider.code,
                provider_name=provider.name,
                monogram=provider.monogram,
                name=scanner.name,
                description=scanner.description,
                category=scanner.category,
                price_inr=money(scanner.price_inr),
                billing_frequency=scanner.billing_frequency,
                entitlement_status=status,  # type: ignore[arg-type]
                activation_method=method,
            )
        )
    return catalogue


def sync_mock_feed(db: Session, *, correlation_id: str | None) -> MockFeedSyncOut:
    if get_settings().environment not in {"development", "test"}:
        raise AppError(404, "not_found", "Not found.")
    scanner = db.scalar(
        select(Scanner)
        .join(ScannerProvider, Scanner.provider_id == ScannerProvider.id)
        .where(ScannerProvider.code == MockManiAdapter.provider_code, Scanner.code == SCANNER_CODE)
    )
    if scanner is None:
        raise AppError(409, "catalog_not_seeded", "The scanner catalogue is missing. Run python -m app.seed.")
    if scanner_feed_mode(db, scanner.id) != "mock":
        raise AppError(
            409,
            "sample_feed_closed",
            "This channel is configured for Telegram. Sample calls are not loaded.",
        )
    counts: Counter[str] = Counter()
    for draft in MockManiAdapter().fetch(utcnow()):
        outcome = ingest(db, scanner_id=scanner.id, draft=draft, correlation_id=correlation_id)
        counts[outcome.value] += 1
    db.commit()
    return MockFeedSyncOut(
        created=counts["created"],
        unchanged=counts["unchanged"],
        revised=counts["revised"],
    )
