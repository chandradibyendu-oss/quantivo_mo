from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.errors import AppError
from app.modules.audit.service import record
from app.modules.scanners.models import Scanner
from app.modules.subscriptions.models import ScannerSubscription, SubscriptionEntitlement


def is_entitled(db: Session, user_id: UUID, scanner_id: UUID) -> bool:
    statement = (
        select(SubscriptionEntitlement.id)
        .join(ScannerSubscription, ScannerSubscription.id == SubscriptionEntitlement.subscription_id)
        .where(
            SubscriptionEntitlement.user_id == user_id,
            SubscriptionEntitlement.scanner_id == scanner_id,
            SubscriptionEntitlement.status == "active",
            ScannerSubscription.status == "active",
        )
    )
    return db.scalar(statement) is not None


def entitled_scanner_ids(db: Session, user_id: UUID) -> list[UUID]:
    statement = (
        select(SubscriptionEntitlement.scanner_id)
        .join(ScannerSubscription, ScannerSubscription.id == SubscriptionEntitlement.subscription_id)
        .where(
            SubscriptionEntitlement.user_id == user_id,
            SubscriptionEntitlement.status == "active",
            ScannerSubscription.status == "active",
        )
        .order_by(SubscriptionEntitlement.granted_at.desc())
    )
    return list(db.scalars(statement).all())


def entitlement_status(db: Session, user_id: UUID, scanner_id: UUID) -> tuple[str, str | None]:
    subscription = db.scalar(
        select(ScannerSubscription)
        .where(
            ScannerSubscription.user_id == user_id,
            ScannerSubscription.scanner_id == scanner_id,
            ScannerSubscription.status == "active",
        )
        .order_by(ScannerSubscription.created_at.desc())
    )
    if subscription is None or not is_entitled(db, user_id, scanner_id):
        return "none", None
    return "active", subscription.activation_method


def activate_for_development(
    db: Session,
    *,
    user_id: UUID,
    scanner_id: UUID,
    correlation_id: str | None,
) -> tuple[ScannerSubscription, SubscriptionEntitlement]:
    settings = get_settings()
    if settings.environment not in {"development", "test"} or not settings.dev_activation_enabled:
        raise AppError(403, "activation_unavailable", "Scanner activation is not available in this environment.")

    scanner = db.get(Scanner, scanner_id)
    if scanner is None or scanner.status != "active":
        raise AppError(404, "scanner_not_found", "That scanner is not available.")

    existing = db.scalar(
        select(ScannerSubscription).where(
            ScannerSubscription.user_id == user_id,
            ScannerSubscription.scanner_id == scanner_id,
            ScannerSubscription.status == "active",
        )
    )
    if existing is not None:
        entitlement = db.scalar(
            select(SubscriptionEntitlement).where(
                SubscriptionEntitlement.subscription_id == existing.id,
                SubscriptionEntitlement.status == "active",
            )
        )
        if entitlement is None:
            raise AppError(409, "entitlement_missing", "This subscription has no active entitlement.")
        return existing, entitlement

    now = utcnow()
    subscription = ScannerSubscription(
        user_id=user_id,
        scanner_id=scanner_id,
        status="active",
        activation_method="admin_assisted",
        starts_at=now,
    )
    db.add(subscription)
    db.flush()
    entitlement = SubscriptionEntitlement(
        subscription_id=subscription.id,
        user_id=user_id,
        scanner_id=scanner_id,
        status="active",
        reason="development_activation",
        granted_at=now,
    )
    db.add(entitlement)
    db.flush()
    record(
        db,
        action="subscription.activated",
        entity_type="scanner_subscription",
        entity_id=subscription.id,
        payload={
            "scanner_id": str(scanner_id),
            "activation_method": "admin_assisted",
            "payment_recorded": False,
            "reason": "development_activation",
        },
        actor_user_id=user_id,
        correlation_id=correlation_id,
    )
    db.commit()
    return subscription, entitlement
