import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.deps import Principal
from app.core.errors import AppError
from app.core.money import money
from app.modules.audit.service import commit_and_raise, record
from app.modules.brokers.service import broker_for_trader
from app.modules.feeds.equity_parser import align_prices
from app.modules.identity.models import User
from app.modules.orders.models import BrokerOrder, OrderIntent
from app.modules.orders.schemas import AdminOrderOut, OrderBookOut, OrderIntentOut, OrderPreviewOut
from app.modules.progress.marks import quoted_past_entry, terminal_mark
from app.modules.risk.calculator import RiskInputs, RiskResult, calculate
from app.modules.risk.service import get_profile
from app.modules.signals.clocks import load_clocks
from app.modules.signals.models import Signal
from app.modules.signals.schemas import OrderPreviewIn, OrderRequest, TargetOut
from app.modules.signals.status import derived_status, is_executable
from app.modules.subscriptions.service import is_entitled

_PRICE = re.compile(r"^(?:0|[1-9]\d{0,9})(?:\.\d{1,4})?$")
SAVED = (
    "Saved. Zerodha was not sent this order. "
    "The stop and targets stay inactive until Zerodha confirms them."
)


@dataclass(frozen=True)
class _Ticket:
    side: str
    trigger: Decimal
    stop: Decimal
    targets: list[dict[str, str]]
    quantity: int
    result: RiskResult


def preview_order(db: Session, principal: Principal, body: OrderPreviewIn) -> OrderPreviewOut:
    """Recalculate quantity for the ticket. Nothing is stored."""

    signal = _signal(db, principal, body.signal_id)
    _executable(
        db,
        principal,
        signal,
        _audit_base(signal, body.product, 0, "preview"),
        correlation_id=None,
    )
    profile = get_profile(db, principal.user.id)
    if body.product not in profile.allowed_products:
        raise AppError(422, "product_not_allowed", "Your risk profile does not allow this product.")
    side, trigger, stop, targets = _prices(signal, body)
    result = _risk(signal, profile, side, trigger, stop)
    return OrderPreviewOut(
        ok=result.ok,
        quantity=result.quantity if result.ok else None,
        reason=result.reason,
        side=side,  # type: ignore[arg-type]
        product=body.product,
        trigger_price=money(trigger) or "0.00",
        stop_loss=money(stop) or "0.00",
        targets=[TargetOut(label=item["label"], price=item["price"]) for item in targets],
    )


def confirm_order(
    db: Session,
    principal: Principal,
    body: OrderRequest,
    *,
    correlation_id: str | None,
) -> OrderIntentOut:
    """Store one proposed intent for this call. Do not call the broker."""

    signal = _signal(db, principal, body.signal_id)
    base = _audit_base(signal, body.product, body.quantity, body.idempotency_key)
    _executable(db, principal, signal, base, correlation_id=correlation_id)
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
    side, trigger, stop, targets = _prices(signal, body)
    result = _risk(signal, profile, side, trigger, stop)
    if not result.ok or result.quantity != body.quantity:
        commit_and_raise(
            db,
            AppError(
                409,
                "quantity_mismatch",
                "Quantity does not match the current server-side calculation. "
                "Refresh the signal and try again.",
            ),
            action="order.rejected_validation",
            entity_type="signal",
            entity_id=signal.id,
            payload={**base, "reason": "quantity_mismatch", "server_quantity": result.quantity},
            actor_user_id=principal.user.id,
            correlation_id=correlation_id,
        )
    account, _connection = broker_for_trader(db, principal.user.id, utcnow())
    if account.status != "connected":
        commit_and_raise(
            db,
            AppError(
                409,
                "broker_not_connected",
                "Sign in on Zerodha before preparing an order. No order was created.",
            ),
            action="order.rejected_validation",
            entity_type="signal",
            entity_id=signal.id,
            payload={**base, "reason": "broker_not_connected"},
            actor_user_id=principal.user.id,
            correlation_id=correlation_id,
        )

    ticket = _Ticket(side, trigger, stop, targets, result.quantity or body.quantity, result)
    found = _by_key(db, body.idempotency_key)
    if found is not None:
        if found.user_id != principal.user.id or not _same(found, ticket, body.product):
            raise AppError(
                409,
                "idempotency_conflict",
                "This confirmation was already saved with different prices.",
            )
        return _out(found)
    open_intent = _open_for_call(db, principal.user.id, signal.id)
    if open_intent is not None and _same(open_intent, ticket, body.product):
        return _out(open_intent)
    intent = open_intent or OrderIntent(
        user_id=principal.user.id,
        signal_id=signal.id,
        idempotency_key=body.idempotency_key,
        status="proposed",
        side=ticket.side,
        product=body.product,
        trigger_price=ticket.trigger,
        stop_loss=ticket.stop,
        targets=ticket.targets,
        requested_quantity=ticket.quantity,
        validated_quantity=ticket.quantity,
    )
    _apply(intent, ticket, body)
    if open_intent is None:
        db.add(intent)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        found = _by_key(db, body.idempotency_key) or _open_for_call(
            db, principal.user.id, signal.id
        )
        if found is not None and _same(found, ticket, body.product):
            return _out(found)
        raise AppError(
            409,
            "idempotency_conflict",
            "This confirmation was already saved with different prices.",
        ) from None
    record(
        db,
        action="order.confirmed",
        entity_type="order_intent",
        entity_id=intent.id,
        payload={**base, "side": ticket.side, "status": "proposed"},
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )
    return _out(intent)


def list_orders(db: Session, principal: Principal) -> list[OrderBookOut]:
    """Saved orders for this trader. Nothing is sent to a broker."""

    rows = db.execute(
        select(OrderIntent, Signal)
        .join(Signal, Signal.id == OrderIntent.signal_id)
        .where(OrderIntent.user_id == principal.user.id)
        .order_by(OrderIntent.created_at.desc(), OrderIntent.id.desc())
    ).all()
    return [_book(intent, signal) for intent, signal in rows]


def open_order(db: Session, principal: Principal, signal_id) -> OrderIntentOut:
    _signal(db, principal, signal_id)
    found = _open_for_call(db, principal.user.id, signal_id)
    if found is None:
        raise AppError(404, "order_not_found", "This call has no saved order.")
    return _out(found)


def _signal(db: Session, principal: Principal, signal_id) -> Signal:
    signal = db.get(Signal, signal_id)
    if signal is None or not is_entitled(db, principal.user.id, signal.scanner_id):
        raise AppError(404, "signal_not_found", "That signal is not available.")
    return signal


def _executable(
    db: Session,
    principal: Principal,
    signal: Signal,
    base: dict,
    *,
    correlation_id: str | None,
) -> None:
    moment = utcnow()
    status = derived_status(signal, moment, load_clocks(db))
    blocked = not is_executable(status) or _finished_mark(signal, moment) is not None
    quoted = None if blocked else _quoted_block(signal)
    blocked = blocked or quoted is not None
    if not blocked:
        return
    reason = quoted or (status if not is_executable(status) else _finished_mark(signal, moment))
    commit_and_raise(
        db,
        AppError(409, "signal_not_actionable", "This signal is not executable."),
        action="order.rejected_validation",
        entity_type="signal",
        entity_id=signal.id,
        payload={**base, "reason": reason},
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )


def _prices(signal: Signal, body: OrderPreviewIn | OrderRequest):
    side = getattr(body, "side", None) or signal.side
    if getattr(body, "trigger_price", None) is None:
        trigger = Decimal(signal.trigger_price)
        stop = Decimal(signal.stop_loss)
    else:
        trigger = _price(body.trigger_price)
        stop = _price(body.stop_loss)
    if getattr(body, "targets", None) is None:
        targets = [_stored_target(item) for item in signal.targets]
    else:
        targets = [
            _stored_target({"label": item.label, "price": item.price}) for item in body.targets
        ]
    if not targets:
        raise AppError(422, "invalid_price", "Enter at least one target.")
    return side, trigger, stop, targets


def _risk(signal: Signal, profile, side: str, trigger: Decimal, stop: Decimal) -> RiskResult:
    return calculate(
        RiskInputs(
            side=side,
            trigger_price=trigger,
            stop_loss=stop,
            lot_size=signal.lot_size,
            max_risk_inr=Decimal(profile.max_risk_inr),
            max_quantity=profile.max_quantity,
            max_exposure_inr=(
                None if profile.max_exposure_inr is None else Decimal(profile.max_exposure_inr)
            ),
            capital_allocation_inr=Decimal(profile.capital_allocation_inr),
        )
    )


def _price(value: str | None) -> Decimal:
    if value is None or _PRICE.fullmatch(value) is None:
        raise AppError(422, "invalid_price", "Enter a price greater than zero.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise AppError(422, "invalid_price", "Enter a price greater than zero.") from error
    if parsed <= 0:
        raise AppError(422, "invalid_price", "Enter a price greater than zero.")
    return parsed


def _stored_target(item: dict) -> dict[str, str]:
    label = str(item["label"]).strip()
    return {"label": label, "price": money(_price(str(item["price"]))) or "0.00"}


def _audit_base(signal: Signal, product: str, quantity: int, key: str) -> dict:
    return {
        "signal_id": str(signal.id),
        "product": product,
        "requested_quantity": quantity,
        "idempotency_key": key,
    }


def _by_key(db: Session, key: str) -> OrderIntent | None:
    return db.scalar(select(OrderIntent).where(OrderIntent.idempotency_key == key))


def _open_for_call(db: Session, user_id, signal_id) -> OrderIntent | None:
    return db.scalar(
        select(OrderIntent).where(
            OrderIntent.user_id == user_id,
            OrderIntent.signal_id == signal_id,
            OrderIntent.status == "proposed",
        )
    )


def _same(intent: OrderIntent, ticket: _Ticket, product: str) -> bool:
    return (
        intent.side == ticket.side
        and intent.product == product
        and intent.requested_quantity == ticket.quantity
        and money(intent.trigger_price) == (money(ticket.trigger) or "0.00")
        and money(intent.stop_loss) == (money(ticket.stop) or "0.00")
        and list(intent.targets) == ticket.targets
    )


def _apply(intent: OrderIntent, ticket: _Ticket, body: OrderRequest) -> None:
    intent.idempotency_key = body.idempotency_key
    intent.status = "proposed"
    intent.side = ticket.side
    intent.product = body.product
    intent.trigger_price = ticket.trigger
    intent.stop_loss = ticket.stop
    intent.targets = ticket.targets
    intent.requested_quantity = ticket.quantity
    intent.validated_quantity = ticket.quantity
    intent.rejection_reason = None


def list_admin_orders(db: Session) -> list[AdminOrderOut]:
    """Proposed intents that have not been sent to a broker, newest first."""

    sent = select(BrokerOrder.id).where(BrokerOrder.order_intent_id == OrderIntent.id).exists()
    rows = db.execute(
        select(OrderIntent, Signal, User)
        .join(Signal, Signal.id == OrderIntent.signal_id)
        .join(User, User.id == OrderIntent.user_id)
        .where(OrderIntent.status == "proposed", ~sent)
        .order_by(OrderIntent.created_at.desc(), OrderIntent.id.desc())
    ).all()
    return [
        AdminOrderOut(
            id=intent.id,
            signal_id=intent.signal_id,
            symbol=signal.symbol,
            side=intent.side,  # type: ignore[arg-type]
            product=intent.product,  # type: ignore[arg-type]
            quantity=intent.validated_quantity or intent.requested_quantity,
            trigger_price=money(intent.trigger_price) or "0.00",
            stop_loss=money(intent.stop_loss) or "0.00",
            status="proposed",
            phone_e164=user.phone_e164,
            saved_at=intent.created_at,
        )
        for intent, signal, user in rows
    ]


def delete_proposed_order(
    db: Session,
    *,
    order_id: UUID,
    actor_user_id: UUID,
    correlation_id: str | None,
) -> None:
    """Remove one unsent proposed intent. The call stays, and Zerodha is not called."""

    intent = db.get(OrderIntent, order_id)
    if intent is None:
        raise AppError(404, "order_not_found", "That saved order is not in the list.")
    sent = db.scalar(
        select(func.count())
        .select_from(BrokerOrder)
        .where(BrokerOrder.order_intent_id == intent.id)
    )
    if intent.status != "proposed" or sent:
        raise AppError(
            409,
            "order_already_sent",
            "This order was sent onward. It stays in the list.",
        )
    signal = db.get(Signal, intent.signal_id)
    record(
        db,
        action="order.deleted",
        entity_type="order_intent",
        entity_id=intent.id,
        payload={
            "signal_id": str(intent.signal_id),
            "symbol": "" if signal is None else signal.symbol,
            "side": intent.side,
            "product": intent.product,
            "quantity": intent.validated_quantity or intent.requested_quantity,
            "status": "proposed",
            "user_id": str(intent.user_id),
        },
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
    )
    db.delete(intent)
    db.flush()


def _book(intent: OrderIntent, signal: Signal) -> OrderBookOut:
    return OrderBookOut(
        id=intent.id,
        signal_id=intent.signal_id,
        symbol=signal.symbol,
        exchange=signal.exchange,
        status=intent.status,
        side=intent.side,  # type: ignore[arg-type]
        product=intent.product,  # type: ignore[arg-type]
        quantity=intent.validated_quantity or intent.requested_quantity,
        trigger_price=money(intent.trigger_price) or "0.00",
        stop_loss=money(intent.stop_loss) or "0.00",
        targets=[TargetOut(label=item["label"], price=item["price"]) for item in intent.targets],
        saved_at=intent.created_at,
        message=SAVED,
    )


def _out(intent: OrderIntent) -> OrderIntentOut:
    return OrderIntentOut(
        id=intent.id,
        signal_id=intent.signal_id,
        status="proposed",
        side=intent.side,  # type: ignore[arg-type]
        product=intent.product,  # type: ignore[arg-type]
        quantity=intent.validated_quantity or intent.requested_quantity,
        trigger_price=money(intent.trigger_price) or "0.00",
        stop_loss=money(intent.stop_loss) or "0.00",
        targets=[TargetOut(label=item["label"], price=item["price"]) for item in intent.targets],
        message=SAVED,
    )


def _quoted_block(signal: Signal) -> str | None:
    if signal.segment.casefold() != "equity" or not signal.targets:
        return None
    try:
        stop = Decimal(signal.stop_loss)
        targets = [Decimal(item["price"]) for item in signal.targets]
        trigger = Decimal(signal.trigger_price)
    except (InvalidOperation, KeyError, TypeError, IndexError):
        return None
    from app.modules.quotes.fyers import read_last_prices

    batch = read_last_prices([(signal.exchange, signal.symbol)])
    price = batch.prices.get((signal.exchange, signal.symbol))
    _trigger, stop, targets = align_prices(signal.side, trigger, stop, targets, price)
    if not targets:
        return None
    return quoted_past_entry(signal.side, price, stop, targets[0])


def _finished_mark(signal: Signal, moment) -> str | None:
    try:
        targets = [Decimal(item["price"]) for item in signal.targets]
        trigger = Decimal(signal.trigger_price)
        stop = Decimal(signal.stop_loss)
        trigger, stop, targets = align_prices(signal.side, trigger, stop, targets)
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
