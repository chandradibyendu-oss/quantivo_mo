from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.deps import Principal
from app.core.errors import AppError
from app.modules.audit.service import commit_and_raise
from app.modules.brokers.service import get_simulated_connection
from app.modules.progress.marks import terminal_mark
from app.modules.risk.calculator import RiskInputs, calculate
from app.modules.risk.service import get_profile
from app.modules.signals.clocks import load_clocks
from app.modules.signals.models import Signal
from app.modules.signals.schemas import OrderRequest
from app.modules.signals.status import derived_status, is_executable
from app.modules.subscriptions.service import is_entitled


def refuse_order(db: Session, principal: Principal, body: OrderRequest, *, correlation_id: str | None) -> None:
    """Validate the request, audit the refusal, and do not persist an order."""

    signal = db.get(Signal, body.signal_id)
    if signal is None or not is_entitled(db, principal.user.id, signal.scanner_id):
        raise AppError(404, "signal_not_found", "That signal is not available.")

    base = {
        "signal_id": str(signal.id),
        "product": body.product,
        "requested_quantity": body.quantity,
        "idempotency_key": body.idempotency_key,
    }
    moment = utcnow()
    status = derived_status(signal, moment, load_clocks(db))
    if not is_executable(status):
        commit_and_raise(
            db,
            AppError(409, "signal_not_actionable", "This signal is not executable."),
            action="order.rejected_validation",
            entity_type="signal",
            entity_id=signal.id,
            payload={**base, "reason": status},
            actor_user_id=principal.user.id,
            correlation_id=correlation_id,
        )
    finished = _finished_mark(signal, moment)
    if finished is not None:
        commit_and_raise(
            db,
            AppError(409, "signal_not_actionable", "This signal is not executable."),
            action="order.rejected_validation",
            entity_type="signal",
            entity_id=signal.id,
            payload={**base, "reason": finished},
            actor_user_id=principal.user.id,
            correlation_id=correlation_id,
        )

    profile = get_profile(db, principal.user.id)
    if body.product not in profile.allowed_products:
        commit_and_raise(
            db,
            AppError(422, "product_not_allowed", "Your risk profile does not allow this product."),
            action="order.rejected_validation",
            entity_type="signal",
            entity_id=signal.id,
            payload={**base, "reason": "product_not_allowed"},
            actor_user_id=principal.user.id,
            correlation_id=correlation_id,
        )

    result = calculate(
        RiskInputs(
            side=signal.side,
            trigger_price=Decimal(signal.trigger_price),
            stop_loss=Decimal(signal.stop_loss),
            lot_size=signal.lot_size,
            max_risk_inr=Decimal(profile.max_risk_inr),
            max_quantity=profile.max_quantity,
            max_exposure_inr=None if profile.max_exposure_inr is None else Decimal(profile.max_exposure_inr),
            capital_allocation_inr=Decimal(profile.capital_allocation_inr),
        )
    )
    if not result.ok or result.quantity != body.quantity:
        commit_and_raise(
            db,
            AppError(
                409,
                "quantity_mismatch",
                "Quantity does not match the current server-side calculation. Refresh the signal and try again.",
            ),
            action="order.rejected_validation",
            entity_type="signal",
            entity_id=signal.id,
            payload={**base, "reason": "quantity_mismatch", "server_quantity": result.quantity},
            actor_user_id=principal.user.id,
            correlation_id=correlation_id,
        )

    connection = get_simulated_connection(db, principal.user.id)
    if connection is None or connection.status != "connected":
        commit_and_raise(
            db,
            AppError(409, "broker_not_connected", "Connect a broker before preparing an order. No order was created."),
            action="order.rejected_validation",
            entity_type="signal",
            entity_id=signal.id,
            payload={**base, "reason": "broker_not_connected"},
            actor_user_id=principal.user.id,
            correlation_id=correlation_id,
        )

    commit_and_raise(
        db,
        AppError(
            403,
            "trading_disabled",
            "Order placement is disabled. The simulated broker can record a connection, but it does not accept, fill, or protect orders.",
        ),
        action="order.refused",
        entity_type="signal",
        entity_id=signal.id,
        payload={**base, "reason": "trading_disabled"},
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )


def _finished_mark(signal: Signal, moment) -> str | None:
    try:
        targets = [Decimal(item["price"]) for item in signal.targets]
        trigger = Decimal(signal.trigger_price)
        stop = Decimal(signal.stop_loss)
    except (InvalidOperation, KeyError, TypeError):
        return None
    return terminal_mark(
        exchange=signal.exchange,
        symbol=signal.symbol,
        segment=signal.segment,
        side=signal.side,
        trigger=trigger,
        stop=stop,
        targets=targets,
        published_at=signal.published_at,
        now=moment,
    )
