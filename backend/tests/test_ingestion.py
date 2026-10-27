from dataclasses import replace
from decimal import Decimal

from sqlalchemy import func, select

from app.core.database import utcnow
from app.modules.scanners.mock_mani import SCANNER_CODE, MockManiAdapter
from app.modules.scanners.models import Scanner
from app.modules.signals.models import Signal
from app.modules.signals.service import IngestOutcome, ingest


def test_revision_updates_content_without_changing_publication_time(db):
    scanner = db.scalar(select(Scanner).where(Scanner.code == SCANNER_CODE))
    draft = MockManiAdapter().fetch(utcnow())[0]
    assert ingest(db, scanner_id=scanner.id, draft=draft, correlation_id="test") is IngestOutcome.CREATED
    assert ingest(db, scanner_id=scanner.id, draft=draft, correlation_id="test") is IngestOutcome.UNCHANGED
    db.commit()
    signal = db.scalar(select(Signal).where(Signal.external_ref == draft.external_ref))
    published_at = signal.published_at
    revised = replace(draft, stop_loss=Decimal("2400.00"))
    assert ingest(db, scanner_id=scanner.id, draft=revised, correlation_id="test") is IngestOutcome.REVISED
    db.commit()
    db.refresh(signal)
    assert signal.stop_loss == Decimal("2400.00")
    assert signal.published_at == published_at
    assert db.scalar(select(func.count()).select_from(Signal)) == 1


def test_a_repeat_restores_a_note_the_hash_already_records(db):
    scanner = db.scalar(select(Scanner).where(Scanner.code == SCANNER_CODE))
    draft = replace(
        MockManiAdapter().fetch(utcnow())[0],
        provider_note="target_hit=2026-10-27 10:00",
    )
    created = ingest(db, scanner_id=scanner.id, draft=draft, correlation_id="test")
    assert created is IngestOutcome.CREATED
    db.commit()
    signal = db.scalar(select(Signal).where(Signal.external_ref == draft.external_ref))
    signal.provider_note = None
    db.commit()
    restored = ingest(db, scanner_id=scanner.id, draft=draft, correlation_id="test")
    assert restored is IngestOutcome.REVISED
    db.commit()
    db.refresh(signal)
    assert signal.provider_note == "target_hit=2026-10-27 10:00"
