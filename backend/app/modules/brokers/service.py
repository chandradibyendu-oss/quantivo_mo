from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.modules.audit.service import record
from app.modules.brokers.kite import (
    app_saved,
    cleared_message,
    connected_message,
    describe,
    disconnected_message,
    expired_message,
)
from app.modules.brokers.kite_store import (
    clear_access_token,
    clear_access_tokens,
    read_access_token,
)
from app.modules.brokers.models import BrokerAccount, BrokerConnection

ZERODHA = "zerodha"


def broker_for_trader(db: Session, user_id: UUID, now):
    account = zerodha_account(db, user_id, now)
    return account, get_zerodha_connection(db, user_id)


def get_zerodha_connection(db: Session, user_id: UUID) -> BrokerConnection | None:
    return db.scalar(
        select(BrokerConnection).where(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker_code == ZERODHA,
        )
    )


def zerodha_account(db: Session, user_id: UUID, now):
    connection = get_zerodha_connection(db, user_id)
    token = read_access_token(str(user_id))
    status = connection.status if connection is not None else None
    client_id = connection.external_account_ref if connection is not None else None
    signed_in_at = connection.last_authenticated_at if connection is not None else None
    if status == "connected" and not token:
        status = "expired"
    if not app_saved():
        return describe(app_ready=False, status=None, client_id=None, signed_in_at=None, now=now)
    account = describe(
        app_ready=True,
        status=status,
        client_id=client_id,
        signed_in_at=signed_in_at,
        now=now,
    )
    if connection is not None and connection.status == "connected" and account.status == "expired":
        clear_access_token(str(user_id))
        connection.status = "expired"
        connection.status_message = expired_message()
        db.commit()
    return account


def record_zerodha(
    db: Session,
    user_id: UUID,
    *,
    client_id: str,
    exchanges: list[str],
    session_end,
    correlation_id: str | None,
) -> BrokerConnection:
    connection = get_zerodha_connection(db, user_id)
    message = connected_message(session_end, client_id)
    if connection is None:
        connection = BrokerConnection(
            user_id=user_id,
            broker_code=ZERODHA,
            status="connected",
            display_name="Zerodha",
            external_account_ref=client_id,
            last_authenticated_at=utcnow(),
            status_message=message,
        )
        db.add(connection)
        db.flush()
        db.add(
            BrokerAccount(
                connection_id=connection.id,
                external_account_id=client_id,
                segments=exchanges,
            )
        )
    else:
        connection.status = "connected"
        connection.display_name = "Zerodha"
        connection.external_account_ref = client_id
        connection.last_authenticated_at = utcnow()
        connection.status_message = message
        account = db.scalar(
            select(BrokerAccount).where(BrokerAccount.connection_id == connection.id)
        )
        if account is None:
            db.add(
                BrokerAccount(
                    connection_id=connection.id,
                    external_account_id=client_id,
                    segments=exchanges,
                )
            )
        else:
            account.external_account_id = client_id
            account.segments = exchanges
    record(
        db,
        action="broker.zerodha_connected",
        entity_type="broker_connection",
        entity_id=connection.id,
        payload={
            "broker_code": ZERODHA,
            "client_id": client_id,
            "session_until": session_end.date().isoformat(),
        },
        actor_user_id=user_id,
        correlation_id=correlation_id,
    )
    db.commit()
    return connection


def disconnect_zerodha(
    db: Session,
    user_id: UUID,
    *,
    correlation_id: str | None,
) -> BrokerConnection:
    clear_access_token(str(user_id))
    connection = get_zerodha_connection(db, user_id)
    message = disconnected_message()
    if connection is None:
        connection = BrokerConnection(
            user_id=user_id,
            broker_code=ZERODHA,
            status="disconnected",
            display_name="Zerodha",
            status_message=message,
        )
        db.add(connection)
        db.flush()
    else:
        connection.status = "disconnected"
        connection.status_message = message
    record(
        db,
        action="broker.zerodha_disconnected",
        entity_type="broker_connection",
        entity_id=connection.id,
        payload={"broker_code": ZERODHA},
        actor_user_id=user_id,
        correlation_id=correlation_id,
    )
    db.commit()
    return connection


def clear_zerodha_sessions(
    db: Session,
    *,
    actor_user_id: UUID,
    correlation_id: str | None,
    message: str | None = None,
) -> None:
    clear_access_tokens()
    rows = list(
        db.scalars(select(BrokerConnection).where(BrokerConnection.broker_code == ZERODHA)).all()
    )
    message = message or cleared_message()
    for connection in rows:
        connection.status = "disconnected"
        connection.status_message = message
    record(
        db,
        action="broker.zerodha_app_cleared",
        entity_type="broker_connection",
        entity_id=None,
        payload={"broker_code": ZERODHA, "sessions_cleared": len(rows)},
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
    )
    db.commit()


def list_connections(db: Session, user_id: UUID) -> list[BrokerConnection]:
    return list(
        db.scalars(
            select(BrokerConnection)
            .where(BrokerConnection.user_id == user_id)
            .order_by(BrokerConnection.created_at)
        ).all()
    )
