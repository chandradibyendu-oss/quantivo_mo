"""Source channels and the trader's registration for each one."""

import re
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.audit.service import record
from app.modules.feeds.models import SourceFeed
from app.modules.orders.models import OrderIntent
from app.modules.scanners.models import ChannelRegistration, Scanner, ScannerProvider, SourceChannel
from app.modules.signals.models import Signal
from app.modules.subscriptions.models import SubscriptionEntitlement

_SEGMENTS = {"equity", "fno", "commodity"}


def list_scanner_channels(db: Session, scanner_id: UUID) -> list[SourceChannel]:
    return list(
        db.scalars(
            select(SourceChannel)
            .where(SourceChannel.scanner_id == scanner_id, SourceChannel.status == "active")
            .order_by(SourceChannel.name)
        ).all()
    )


def visible_channel_ids(db: Session, *, user_id: UUID, scanner_id: UUID) -> set[UUID]:
    """Channels whose calls this trader may see.

    One channel and no registration rows keeps the original scanner grant.
    A second channel is hidden until the trader registers for it.
    """

    channels = list_scanner_channels(db, scanner_id)
    if not channels:
        return set()
    channel_ids = [channel.id for channel in channels]
    rows = db.scalars(
        select(ChannelRegistration).where(
            ChannelRegistration.user_id == user_id,
            ChannelRegistration.source_channel_id.in_(channel_ids),
        )
    ).all()
    if rows:
        return {row.source_channel_id for row in rows if row.status == "active"}
    if len(channels) == 1:
        return {channels[0].id}
    return set()


def create_scanner(
    db: Session,
    *,
    provider_name: str,
    name: str,
    category: str,
    description: str | None,
    actor_user_id: UUID,
    correlation_id: str | None,
) -> tuple[Scanner, ScannerProvider]:
    provider_label = " ".join(provider_name.split())
    scanner_label = " ".join(name.split())
    if (
        not provider_label
        or len(provider_label) > 120
        or not scanner_label
        or len(scanner_label) > 120
    ):
        raise AppError(422, "invalid_scanner", "Enter the provider name and the scanner name.")
    category_label = " ".join(category.split()) or "Calls"
    if len(category_label) > 64:
        raise AppError(422, "invalid_scanner", "Use a shorter category.")
    provider = db.scalar(
        select(ScannerProvider).where(
            func.lower(ScannerProvider.name) == provider_label.lower(),
            ScannerProvider.status == "active",
        )
    )
    if provider is None:
        taken = set(db.scalars(select(ScannerProvider.code)).all())
        provider = ScannerProvider(
            code=_code_for(provider_label, "provider", taken),
            name=provider_label,
            monogram=_monogram(provider_label),
            description=f"{provider_label} publishes scanners in this catalogue.",
            status="active",
        )
        db.add(provider)
        db.flush()
    taken_scanners = set(
        db.scalars(select(Scanner.code).where(Scanner.provider_id == provider.id)).all()
    )
    scanner = Scanner(
        provider_id=provider.id,
        code=_code_for(scanner_label, "scanner", taken_scanners),
        name=scanner_label,
        description=(
            _description(description)
            or f"{scanner_label} from {provider.name}. Channels are added separately."
        ),
        category=category_label,
        price_inr=None,
        billing_frequency=None,
        status="active",
    )
    db.add(scanner)
    db.flush()
    record(
        db,
        action="scanner.created",
        entity_type="scanner",
        entity_id=scanner.id,
        payload={
            "provider_code": provider.code,
            "scanner_code": scanner.code,
            "name": scanner_label,
        },
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
    )
    return scanner, provider


def rename_scanner(
    db: Session,
    *,
    scanner_id: UUID,
    name: str,
    provider_name: str | None,
    description: str | None,
    actor_user_id: UUID,
    correlation_id: str | None,
) -> tuple[Scanner, ScannerProvider]:
    cleaned = " ".join(name.split())
    if not cleaned or len(cleaned) > 120:
        raise AppError(422, "invalid_scanner", "Enter a scanner name.")
    scanner = db.get(Scanner, scanner_id)
    if scanner is None or scanner.status != "active":
        raise AppError(404, "scanner_not_found", "That scanner is not in the catalogue.")
    provider = db.get(ScannerProvider, scanner.provider_id)
    if provider is None:
        raise AppError(404, "scanner_not_found", "That scanner is not in the catalogue.")
    previous_name = scanner.name
    previous_provider = provider.name
    provider = _place_provider(db, scanner, provider, provider_name)
    written = _description(description)
    if written is None:
        generated = f"{previous_name} from {previous_provider}. Channels are added separately."
        if scanner.description == generated:
            scanner.description = f"{cleaned} from {provider.name}. Channels are added separately."
    else:
        scanner.description = written
    scanner.name = cleaned
    record(
        db,
        action="scanner.renamed",
        entity_type="scanner",
        entity_id=scanner.id,
        payload={
            "scanner_code": scanner.code,
            "name": cleaned,
            "provider_name": provider.name,
        },
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
    )
    return scanner, provider


def delete_scanner(
    db: Session,
    *,
    scanner_id: UUID,
    actor_user_id: UUID,
    correlation_id: str | None,
) -> None:
    """Remove a scanner after its channels. An order record keeps the scanner."""

    scanner = db.get(Scanner, scanner_id)
    if scanner is None or scanner.status != "active":
        raise AppError(404, "scanner_not_found", "That scanner is not in the catalogue.")
    channels = list_scanner_channels(db, scanner.id)
    for channel in channels:
        delete_source_channel(
            db,
            channel_id=channel.id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )
    record(
        db,
        action="scanner.deleted",
        entity_type="scanner",
        entity_id=scanner.id,
        payload={"scanner_code": scanner.code, "name": scanner.name},
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
    )
    db.delete(scanner)
    db.flush()


def _description(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = " ".join(raw.split())
    if not cleaned or len(cleaned) > 400:
        raise AppError(422, "invalid_scanner", "Enter a description of at most 400 characters.")
    return cleaned


def _place_provider(
    db: Session,
    scanner: Scanner,
    provider: ScannerProvider,
    provider_name: str | None,
) -> ScannerProvider:
    if provider_name is None:
        return provider
    label = " ".join(provider_name.split())
    if not label or len(label) > 120:
        raise AppError(422, "invalid_scanner", "Enter the provider name.")
    if label.lower() == provider.name.lower():
        provider.name = label
        return provider
    other = db.scalar(
        select(ScannerProvider).where(
            func.lower(ScannerProvider.name) == label.lower(),
            ScannerProvider.status == "active",
        )
    )
    if other is not None and other.id != provider.id:
        taken = set(db.scalars(select(Scanner.code).where(Scanner.provider_id == other.id)).all())
        if scanner.code in taken:
            scanner.code = _code_for(scanner.name, "scanner", taken)
        scanner.provider_id = other.id
        return other
    provider.name = label
    provider.monogram = _monogram(label)
    return provider


def create_source_channel(
    db: Session,
    *,
    name: str,
    segment: str,
    actor_user_id: UUID,
    correlation_id: str | None,
    scanner_id: UUID | None = None,
) -> tuple[SourceChannel, Scanner, SourceFeed]:
    cleaned = " ".join(name.split())
    if not cleaned or len(cleaned) > 120:
        raise AppError(422, "invalid_channel", "Enter a channel name.")
    if segment not in _SEGMENTS:
        raise AppError(422, "invalid_channel", "Choose equity, fno, or commodity.")
    scanner = _chosen_scanner(db, scanner_id)
    if scanner is None:
        raise AppError(422, "scanner_required", "Choose the scanner for this channel.")
    existing = list_scanner_channels(db, scanner.id)
    _materialize_single_grant(db, scanner_id=scanner.id, channels=existing)
    taken = {channel.code for channel in existing}
    code = _code_for(cleaned, segment, taken)
    channel = SourceChannel(
        scanner_id=scanner.id,
        code=code,
        name=cleaned,
        segment=segment,
        horizon_aliases=[],
        status="active",
    )
    db.add(channel)
    db.flush()
    feed = SourceFeed(source_channel_id=channel.id, kind="none", status="active", options={})
    db.add(feed)
    db.flush()
    record(
        db,
        action="channel.created",
        entity_type="source_channel",
        entity_id=channel.id,
        payload={"channel_code": code, "segment": segment, "name": cleaned},
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
    )
    return channel, scanner, feed


def rename_source_channel(
    db: Session,
    *,
    channel_id: UUID,
    name: str,
    actor_user_id: UUID,
    correlation_id: str | None,
) -> tuple[SourceChannel, Scanner, SourceFeed]:
    cleaned = " ".join(name.split())
    if not cleaned or len(cleaned) > 120:
        raise AppError(422, "invalid_channel", "Enter a channel name.")
    row = _channel_feed(db, channel_id)
    if row is None:
        raise AppError(404, "channel_not_found", "That source channel is not in the catalogue.")
    channel, scanner, feed = row
    channel.name = cleaned
    record(
        db,
        action="channel.renamed",
        entity_type="source_channel",
        entity_id=channel.id,
        payload={"channel_code": channel.code, "name": cleaned},
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
    )
    return channel, scanner, feed


def stored_call_count(db: Session, channel_id: UUID) -> int:
    counted = db.scalar(
        select(func.count()).select_from(Signal).where(Signal.source_channel_id == channel_id)
    )
    return int(counted or 0)


def delete_source_channel(
    db: Session,
    *,
    channel_id: UUID,
    actor_user_id: UUID,
    correlation_id: str | None,
) -> None:
    """Remove a channel and its stored calls. An order record keeps the channel."""

    row = _channel_feed(db, channel_id)
    if row is None:
        raise AppError(404, "channel_not_found", "That source channel is not in the catalogue.")
    channel, _scanner, _feed = row
    orders = db.scalar(
        select(func.count())
        .select_from(OrderIntent)
        .join(Signal, Signal.id == OrderIntent.signal_id)
        .where(Signal.source_channel_id == channel.id)
    )
    if orders:
        raise AppError(
            409,
            "channel_has_orders",
            "This channel has an order record. It stays in the catalogue.",
        )
    calls = stored_call_count(db, channel.id)
    record(
        db,
        action="channel.deleted",
        entity_type="source_channel",
        entity_id=channel.id,
        payload={"channel_code": channel.code, "name": channel.name, "stored_calls": calls},
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
    )
    db.execute(delete(Signal).where(Signal.source_channel_id == channel.id))
    db.delete(channel)
    db.flush()


def trader_channels(
    db: Session, *, user_id: UUID, scanner_id: UUID
) -> list[tuple[SourceChannel, bool]]:
    visible = visible_channel_ids(db, user_id=user_id, scanner_id=scanner_id)
    return [(channel, channel.id in visible) for channel in list_scanner_channels(db, scanner_id)]


def set_registration(
    db: Session,
    *,
    user_id: UUID,
    scanner_id: UUID,
    channel_id: UUID,
    active: bool,
    correlation_id: str | None,
) -> SourceChannel:
    entitled = db.scalar(
        select(SubscriptionEntitlement.id).where(
            SubscriptionEntitlement.user_id == user_id,
            SubscriptionEntitlement.scanner_id == scanner_id,
            SubscriptionEntitlement.status == "active",
        )
    )
    if entitled is None:
        raise AppError(403, "not_entitled", "Activate the scanner before registering a channel.")
    channel = db.get(SourceChannel, channel_id)
    if channel is None or channel.scanner_id != scanner_id or channel.status != "active":
        raise AppError(404, "channel_not_found", "That source channel is not in the catalogue.")
    row = db.scalar(
        select(ChannelRegistration).where(
            ChannelRegistration.user_id == user_id,
            ChannelRegistration.source_channel_id == channel.id,
        )
    )
    if row is None:
        row = ChannelRegistration(
            user_id=user_id,
            source_channel_id=channel.id,
            status="active" if active else "inactive",
        )
        db.add(row)
    else:
        row.status = "active" if active else "inactive"
    db.flush()
    record(
        db,
        action="channel.registered" if active else "channel.unregistered",
        entity_type="source_channel",
        entity_id=channel.id,
        payload={"channel_code": channel.code},
        actor_user_id=user_id,
        correlation_id=correlation_id,
    )
    return channel


def _materialize_single_grant(
    db: Session, *, scanner_id: UUID, channels: list[SourceChannel]
) -> None:
    """Keep the current channel open for entitled traders before another channel is added."""

    if len(channels) != 1:
        return
    entitled = db.scalars(
        select(SubscriptionEntitlement.user_id).where(
            SubscriptionEntitlement.scanner_id == scanner_id,
            SubscriptionEntitlement.status == "active",
        )
    ).all()
    for account_id in set(entitled):
        already = db.scalar(
            select(ChannelRegistration.id).where(
                ChannelRegistration.user_id == account_id,
                ChannelRegistration.source_channel_id == channels[0].id,
            )
        )
        if already is None:
            db.add(
                ChannelRegistration(
                    user_id=account_id,
                    source_channel_id=channels[0].id,
                    status="active",
                )
            )
    db.flush()


def _channel_feed(db: Session, channel_id: UUID):
    return db.execute(
        select(SourceChannel, Scanner, SourceFeed)
        .join(Scanner, Scanner.id == SourceChannel.scanner_id)
        .join(SourceFeed, SourceFeed.source_channel_id == SourceChannel.id)
        .where(SourceChannel.id == channel_id)
    ).one_or_none()


def _chosen_scanner(db: Session, scanner_id: UUID | None) -> Scanner | None:
    if scanner_id is not None:
        scanner = db.get(Scanner, scanner_id)
        if scanner is None or scanner.status != "active":
            raise AppError(404, "scanner_not_found", "That scanner is not in the catalogue.")
        return scanner
    scanners = list(
        db.scalars(select(Scanner).where(Scanner.status == "active").order_by(Scanner.name)).all()
    )
    if len(scanners) == 1:
        return scanners[0]
    return None


def _monogram(name: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", name) if part]
    if not parts:
        return "S"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[1][0]}".upper()


def _code_for(name: str, segment: str, taken: set[str]) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or segment
    code = raw
    number = 2
    while code in taken:
        suffix = f"-{number}"
        code = f"{raw[: 64 - len(suffix)]}{suffix}"
        number += 1
    return code
