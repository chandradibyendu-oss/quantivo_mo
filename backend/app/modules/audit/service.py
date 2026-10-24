import logging
import uuid

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.audit.models import AuditEvent

logger = logging.getLogger("quantivo.audit")

_FORBIDDEN_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "otp",
    "authorization",
    "credential",
    "code_hash",
)


def _forbidden(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _FORBIDDEN_FRAGMENTS)


def assert_payload_safe(payload: dict) -> None:
    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if _forbidden(str(key)):
                    logger.error("audit payload rejected")
                    raise AppError(
                        500,
                        "audit_rejected",
                        "The action could not be recorded safely.",
                    )
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    payload: dict,
    actor_user_id: uuid.UUID | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    assert_payload_safe(payload)
    event = AuditEvent(
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
        correlation_id=correlation_id,
    )
    db.add(event)
    return event


def commit_and_raise(
    db: Session,
    error: AppError,
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    payload: dict,
    actor_user_id: uuid.UUID | None = None,
    correlation_id: str | None = None,
) -> None:
    record(
        db,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
    )
    db.commit()
    raise error
