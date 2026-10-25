from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.errors import AppError
from app.core.money import money
from app.modules.brokers.service import broker_for_trader
from app.modules.feeds.service import scanner_feed_mode
from app.modules.feeds.window import quote_label, session_day
from app.modules.progress.candles import session_candles
from app.modules.progress.marks import CLOSED_MARKS, apply_progress
from app.modules.quotes.fyers import QuoteSource, read_last_prices
from app.modules.risk.calculator import FORMULA, FUNDS_NOTE, RiskInputs, calculate
from app.modules.risk.models import RiskProfile
from app.modules.risk.service import get_profile
from app.modules.scanners.channels import list_scanner_channels, visible_channel_ids
from app.modules.scanners.models import Scanner, ScannerProvider, SourceChannel
from app.modules.signals.clocks import CallClocks, load_clocks
from app.modules.signals.models import Signal
from app.modules.signals.schemas import (
    BrokerSummary,
    CandleOut,
    ProviderValues,
    QuantivoValues,
    SignalCard,
    SignalChartOut,
    SignalDetail,
    SignalListOut,
    TargetOut,
)
from app.modules.signals.status import derived_status, guide_for, is_executable, warning_for
from app.modules.subscriptions.service import entitled_scanner_ids, is_entitled


def _reward_risk(trigger: Decimal, stop: Decimal, target: Decimal) -> str | None:
    risk = abs(trigger - stop)
    if risk <= 0:
        return None
    ratio = (abs(target - trigger) / risk).quantize(Decimal("0.01"))
    return format(ratio, "f")


def _provider_values(signal: Signal) -> ProviderValues:
    trigger = Decimal(signal.trigger_price)
    stop = Decimal(signal.stop_loss)
    return ProviderValues(
        trigger_price=money(signal.trigger_price) or "0.00",
        stop_loss=money(signal.stop_loss) or "0.00",
        targets=[
            TargetOut(
                label=item["label"],
                price=money(Decimal(item["price"])) or "0.00",
                risk_reward=_reward_risk(trigger, stop, Decimal(item["price"])),
            )
            for item in signal.targets
        ],
        note=signal.provider_note,
    )


def _quantivo_values(
    db: Session,
    user_id: UUID,
    signal: Signal,
    profile: RiskProfile | None = None,
) -> QuantivoValues:
    if profile is None:
        profile = get_profile(db, user_id)
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
    return QuantivoValues(
        suggested_quantity=result.quantity if result.ok else None,
        per_share_risk=money(result.per_share_risk),
        estimated_risk_inr=money(result.risk_amount),
        notional_inr=money(result.notional),
        capital_allocation_inr=money(profile.capital_allocation_inr) or "0.00",
        max_risk_inr=money(profile.max_risk_inr) or "0.00",
        formula=FORMULA,
        funds_check=FUNDS_NOTE,
        unavailable_reason=None if result.ok else result.reason,
    )


def _channel(db: Session, signal: Signal) -> SourceChannel:
    channel = db.get(SourceChannel, signal.source_channel_id)
    if channel is None:
        raise AppError(404, "signal_not_found", "That signal is not available.")
    return channel


def _card(
    db: Session,
    *,
    user_id: UUID,
    signal: Signal,
    scanner: Scanner,
    provider: ScannerProvider,
    now: datetime,
    clocks: CallClocks,
    profile: RiskProfile | None = None,
    channel: SourceChannel | None = None,
) -> SignalCard:
    status = derived_status(signal, now, clocks)
    guide, guide_label, guide_hint = guide_for(signal, now, clocks)
    calculated = _quantivo_values(db, user_id, signal, profile)
    if channel is None:
        channel = _channel(db, signal)
    return SignalCard(
        id=signal.id,
        symbol=signal.symbol,
        exchange=signal.exchange,
        side=signal.side,
        timeframe=signal.timeframe,
        product_hint=signal.product_hint,
        status=status,
        stored_status=signal.status,
        warning=warning_for(status),
        executable=is_executable(status),
        guide=guide,  # type: ignore[arg-type]
        guide_label=guide_label,
        guide_hint=guide_hint,
        published_at=signal.published_at,
        expires_at=signal.expires_at,
        provider_name=provider.name,
        scanner_id=scanner.id,
        scanner_name=scanner.name,
        segment=signal.segment,
        channel_code=channel.code,
        channel_name=channel.name,
        horizon_raw=signal.horizon_raw,
        lot_size=signal.lot_size,
        provider_values=_provider_values(signal),
        quantivo_values=calculated,
        suggested_quantity=calculated.suggested_quantity,
    )


def _bundle(db: Session, scanner_id: UUID) -> tuple[Scanner, ScannerProvider]:
    row = db.execute(
        select(Scanner, ScannerProvider)
        .join(ScannerProvider, Scanner.provider_id == ScannerProvider.id)
        .where(Scanner.id == scanner_id)
    ).one_or_none()
    if row is None:
        raise AppError(404, "scanner_not_found", "That scanner is not available.")
    return row[0], row[1]


def _broker_summary(db: Session, user_id: UUID, now) -> BrokerSummary:
    account, connection = broker_for_trader(db, user_id, now)
    status = "disconnected" if account.status == "not_set" else account.status
    return BrokerSummary(
        code="zerodha",
        status=status,
        last_authenticated_at=None if connection is None else connection.last_authenticated_at,
        message=account.detail,
    )


def list_signals(
    db: Session,
    *,
    user_id: UUID,
    scanner_id: UUID | None,
    view: str,
    channel_id: UUID | None = None,
) -> SignalListOut:
    if scanner_id is None:
        entitled = entitled_scanner_ids(db, user_id)
        scanner_id = entitled[0] if entitled else None
    elif not is_entitled(db, user_id, scanner_id):
        raise AppError(403, "entitlement_required", "Activate this scanner before reading its signals.")

    broker_status = _broker_summary(db, user_id, utcnow()).status
    if scanner_id is None:
        return SignalListOut(
            entitled=False,
            scanner_id=None,
            scanner_name=None,
            provider_name=None,
            provider_monogram=None,
            as_of=None,
            broker_status=broker_status,
            hidden_non_actionable=0,
            signals=[],
        )

    scanner, provider = _bundle(db, scanner_id)
    if not is_entitled(db, user_id, scanner.id):
        raise AppError(403, "entitlement_required", "Activate this scanner before reading its signals.")

    mode = scanner_feed_mode(db, scanner.id)
    channels = list_scanner_channels(db, scanner.id)
    visible = visible_channel_ids(db, user_id=user_id, scanner_id=scanner.id)
    omitted = [channel.name for channel in channels if channel.id not in visible]
    selected_name = None
    registration_required = False
    statement = select(Signal).where(Signal.scanner_id == scanner.id)
    if mode != "mock":
        statement = statement.where(Signal.origin == "channel")
    if channel_id is not None:
        selected = next((channel for channel in channels if channel.id == channel_id), None)
        if selected is None:
            raise AppError(404, "channel_not_found", "That source channel is not in the catalogue.")
        selected_name = selected.name
        omitted = []
        if channel_id not in visible:
            registration_required = True
            statement = statement.where(false())
        else:
            statement = statement.where(Signal.source_channel_id == channel_id)
    elif visible:
        statement = statement.where(Signal.source_channel_id.in_(visible))
    else:
        statement = statement.where(false())
    rows = list(db.scalars(statement.order_by(Signal.published_at.desc())).all())
    now = utcnow()
    clocks = load_clocks(db)
    profile: RiskProfile | None = None
    channel_by_id = {channel.id: channel for channel in channels}
    cards: list[SignalCard] = []
    hidden = 0
    for signal in rows:
        status = derived_status(signal, now, clocks)
        if status != "active":
            hidden += 1
            if view == "actionable":
                continue
        if profile is None:
            profile = get_profile(db, user_id)
        cards.append(
            _card(
                db,
                user_id=user_id,
                signal=signal,
                scanner=scanner,
                provider=provider,
                now=now,
                clocks=clocks,
                profile=profile,
                channel=channel_by_id.get(signal.source_channel_id),
            )
        )
    quote_feed, cards = _with_quotes(cards)
    cards = apply_progress(cards, now=now)
    shown: list[SignalCard] = []
    for card in cards:
        if card.guide in CLOSED_MARKS:
            hidden += 1
            if view == "actionable":
                continue
        shown.append(card)
    cards = shown
    as_of = max((signal.published_at for signal in rows), default=None)
    return SignalListOut(
        entitled=True,
        scanner_id=scanner.id,
        scanner_name=scanner.name,
        provider_name=provider.name,
        provider_monogram=provider.monogram,
        feed_mode=mode,
        feed_connection="mock_seed" if mode == "mock" else mode,
        as_of=as_of,
        broker_status=broker_status,
        hidden_non_actionable=hidden,
        omitted_channels=omitted,
        registration_required=registration_required,
        selected_channel_name=selected_name,
        quote_feed=quote_feed,
        signals=cards,
    )


def _with_quotes(
    cards: list[SignalCard],
    *,
    actionable_only: bool = True,
) -> tuple[QuoteSource, list[SignalCard]]:
    """Quote actionable NSE cash names. A closed list is not sent to Fyers."""
    label = quote_label(utcnow())
    batch = read_last_prices(
        [
            (card.exchange, card.symbol)
            for card in cards
            if _quoted(card, actionable_only=actionable_only)
        ]
    )
    updated: list[SignalCard] = []
    for card in cards:
        if not _quoted(card, actionable_only=actionable_only):
            updated.append(
                card.model_copy(
                    update={
                        "last_price": None,
                        "change_percent": None,
                        "quote_state": "unconfigured",
                        "quote_label": label,
                    }
                )
            )
            continue
        key = (card.exchange, card.symbol)
        price = batch.prices.get(key)
        if price is None:
            state = "missing" if batch.source == "fyers" else batch.source
            updated.append(
                card.model_copy(
                    update={
                        "last_price": None,
                        "change_percent": None,
                        "quote_state": state,
                        "quote_label": label,
                    }
                )
            )
            continue
        updated.append(
            card.model_copy(
                update={
                    "last_price": money(price),
                    "change_percent": money(batch.changes.get(key)),
                    "quote_state": "ready",
                    "quote_label": label,
                }
            )
        )
    return batch.source, updated


def _quoted(card: SignalCard, *, actionable_only: bool) -> bool:
    if card.guide == "no_symbol":
        return False
    if actionable_only and card.status != "active":
        return False
    return True


def get_signal(db: Session, *, user_id: UUID, signal_id: UUID) -> SignalDetail:
    signal = db.get(Signal, signal_id)
    if signal is None or not is_entitled(db, user_id, signal.scanner_id):
        raise AppError(404, "signal_not_found", "That signal is not available.")
    if scanner_feed_mode(db, signal.scanner_id) != "mock" and signal.origin != "channel":
        raise AppError(404, "signal_not_found", "That signal is not available.")
    visible = visible_channel_ids(db, user_id=user_id, scanner_id=signal.scanner_id)
    if signal.source_channel_id not in visible:
        raise AppError(404, "signal_not_found", "That signal is not available.")
    scanner, provider = _bundle(db, signal.scanner_id)
    moment = utcnow()
    card = _card(
        db,
        user_id=user_id,
        signal=signal,
        scanner=scanner,
        provider=provider,
        now=moment,
        clocks=load_clocks(db),
    )
    _feed, quoted = _with_quotes([card], actionable_only=False)
    card = apply_progress(quoted, now=utcnow())[0]
    return SignalDetail(
        **card.model_dump(),
        broker=_broker_summary(db, user_id, moment),
    )


def get_chart(
    db: Session, *, user_id: UUID, signal_id: UUID, interval: Literal["1m", "5m"]
) -> SignalChartOut:
    detail = get_signal(db, user_id=user_id, signal_id=signal_id)
    moment = utcnow()
    state, candles = session_candles(
        exchange=detail.exchange,
        symbol=detail.symbol,
        segment=detail.segment,
        interval=interval,
        now=moment,
    )
    if state == "checking":
        quote_state = "checking"
    elif state == "unconfigured":
        quote_state = "unconfigured"
    elif state == "ready":
        quote_state = "ready" if candles else "missing"
    else:
        quote_state = "unavailable"
    return SignalChartOut(
        symbol=detail.symbol,
        side=detail.side,
        interval=interval,
        session_date=session_day(moment).isoformat(),
        quote_label=detail.quote_label,
        last_price=detail.last_price,
        change_percent=detail.change_percent,
        quote_state=quote_state,
        trigger_price=detail.provider_values.trigger_price,
        stop_loss=detail.provider_values.stop_loss,
        targets=detail.provider_values.targets,
        candles=[CandleOut.model_validate(row) for row in candles],
    )
