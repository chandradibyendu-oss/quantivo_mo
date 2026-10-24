from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.modules.audit.service import record
from app.modules.brokers.models import BrokerAccount, BrokerConnection

SIMULATED = "simulated"
CONNECTED_MESSAGE = "Simulated session. No credentials are stored, and orders are disabled."
DISCONNECTED_MESSAGE = "Disconnected. No broker credentials were stored."


def get_simulated_connection(db: Session, user_id: UUID) -> BrokerConnection | None:
    return db.scalar(
        select(BrokerConnection).where(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker_code == SIMULATED,
        )
    )


def list_connections(db: Session, user_id: UUID) -> list[BrokerConnection]:
    return list(
        db.scalars(
            select(BrokerConnection)
            .where(BrokerConnection.user_id == user_id)
            .order_by(BrokerConnection.created_at)
        ).all()
    )


def connect_simulated(db: Session, user_id: UUID, *, correlation_id: str | None) -> BrokerConnection:
    now = utcnow()
    connection = get_simulated_connection(db, user_id)
    if connection is None:
        connection = BrokerConnection(
            user_id=user_id,
            broker_code=SIMULATED,
            status="connected",
            display_name="Simulated broker",
            external_account_ref=f"SIM-{str(user_id).split('-')[0].upper()}",
            last_authenticated_at=now,
            status_message=CONNECTED_MESSAGE,
        )
        db.add(connection)
        db.flush()
        db.add(
            BrokerAccount(
                connection_id=connection.id,
                external_account_id=connection.external_account_ref or "SIM",
                segments=["NSE"],
            )
        )
    else:
        connection.status = "connected"
        connection.last_authenticated_at = now
        connection.status_message = CONNECTED_MESSAGE
    record(
        db,
        action="broker.simulated_connected",
        entity_type="broker_connection",
        entity_id=connection.id,
        payload={"broker_code": SIMULATED, "login_persisted": False},
        actor_user_id=user_id,
        correlation_id=correlation_id,
    )
    db.commit()
    return connection


def disconnect_simulated(db: Session, user_id: UUID, *, correlation_id: str | None) -> BrokerConnection:
    connection = get_simulated_connection(db, user_id)
    if connection is None:
        connection = BrokerConnection(
            user_id=user_id,
            broker_code=SIMULATED,
            status="disconnected",
            display_name="Simulated broker",
            status_message=DISCONNECTED_MESSAGE,
        )
        db.add(connection)
        db.flush()
    else:
        connection.status = "disconnected"
        connection.status_message = DISCONNECTED_MESSAGE
    record(
        db,
        action="broker.simulated_disconnected",
        entity_type="broker_connection",
        entity_id=connection.id,
        payload={"broker_code": SIMULATED},
        actor_user_id=user_id,
        correlation_id=correlation_id,
    )
    db.commit()
    return connection
