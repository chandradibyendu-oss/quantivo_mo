from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.deps import CorrelationId, Db, Principal, require_permission
from app.modules.feeds.schemas import (
    ChannelCreate,
    ChannelLookupIn,
    ChannelLookupOut,
    ChannelMatchOut,
    ChannelRename,
    FeedOut,
    FeedUpdate,
    ReaderOut,
    ScannerCreate,
    ScannerCreated,
    ScannerRename,
    TelegramLoginOut,
)
from app.modules.feeds.service import list_feeds, reader_state, save_feed, telegram_login_status
from app.modules.feeds.telegram_source import find_joined_channels
from app.modules.scanners.channels import (
    create_scanner,
    create_source_channel,
    delete_scanner,
    delete_source_channel,
    rename_scanner,
    rename_source_channel,
    stored_call_count,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
Reader = Annotated[Principal, Depends(require_permission("admin.feeds.read"))]
Writer = Annotated[Principal, Depends(require_permission("admin.feeds.write"))]


def _out(db, channel, scanner, feed) -> FeedOut:
    state, detail = reader_state(feed)
    return FeedOut(
        channel_id=channel.id,
        scanner_id=scanner.id,
        scanner_name=scanner.name,
        channel_code=channel.code,
        channel_name=channel.name,
        segment=channel.segment,
        kind=feed.kind,
        status=feed.status,
        options=feed.options or {},
        stored_calls=stored_call_count(db, channel.id),
        reader=ReaderOut(state=state, detail=detail),
    )


@router.get("/telegram-login", response_model=TelegramLoginOut)
def telegram_login(principal: Reader) -> TelegramLoginOut:
    del principal
    status, detail = telegram_login_status()
    return TelegramLoginOut(status=status, detail=detail)


@router.post("/telegram-channels/lookup", response_model=ChannelLookupOut)
async def lookup_telegram_channel(body: ChannelLookupIn, principal: Writer) -> ChannelLookupOut:
    del principal
    matches = await find_joined_channels(body.name)
    found = [ChannelMatchOut(channel_id=match.channel_id, title=match.title) for match in matches]
    return ChannelLookupOut(matches=found)


@router.post("/scanners", response_model=ScannerCreated)
def add_scanner(
    body: ScannerCreate,
    principal: Writer,
    db: Db,
    correlation_id: CorrelationId,
) -> ScannerCreated:
    scanner, provider = create_scanner(
        db,
        provider_name=body.provider_name,
        name=body.name,
        category=body.category,
        description=body.description,
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )
    return ScannerCreated(id=scanner.id, name=scanner.name, provider_name=provider.name)


@router.put("/scanners/{scanner_id}", response_model=ScannerCreated)
def rename_catalogue_scanner(
    scanner_id: UUID,
    body: ScannerRename,
    principal: Writer,
    db: Db,
    correlation_id: CorrelationId,
) -> ScannerCreated:
    scanner, provider = rename_scanner(
        db,
        scanner_id=scanner_id,
        name=body.name,
        provider_name=body.provider_name,
        description=body.description,
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )
    return ScannerCreated(id=scanner.id, name=scanner.name, provider_name=provider.name)


@router.delete("/scanners/{scanner_id}", status_code=204)
def remove_catalogue_scanner(
    scanner_id: UUID,
    principal: Writer,
    db: Db,
    correlation_id: CorrelationId,
) -> None:
    delete_scanner(
        db,
        scanner_id=scanner_id,
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )


@router.post("/source-channels", response_model=FeedOut)
def create_channel(
    body: ChannelCreate,
    principal: Writer,
    db: Db,
    correlation_id: CorrelationId,
) -> FeedOut:
    channel, scanner, feed = create_source_channel(
        db,
        name=body.name,
        segment=body.segment,
        scanner_id=body.scanner_id,
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )
    return _out(db, channel, scanner, feed)


@router.put("/source-channels/{channel_id}", response_model=FeedOut)
def rename_channel(
    channel_id: UUID,
    body: ChannelRename,
    principal: Writer,
    db: Db,
    correlation_id: CorrelationId,
) -> FeedOut:
    channel, scanner, feed = rename_source_channel(
        db,
        channel_id=channel_id,
        name=body.name,
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )
    return _out(db, channel, scanner, feed)


@router.delete("/source-channels/{channel_id}", status_code=204)
def remove_channel(
    channel_id: UUID,
    principal: Writer,
    db: Db,
    correlation_id: CorrelationId,
) -> None:
    delete_source_channel(
        db,
        channel_id=channel_id,
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )


@router.get("/source-channels", response_model=list[FeedOut])
def source_channels(principal: Reader, db: Db) -> list[FeedOut]:
    del principal
    return [_out(db, channel, scanner, feed) for channel, scanner, feed in list_feeds(db)]


@router.put("/source-channels/{channel_id}/feed", response_model=FeedOut)
def update_feed(
    channel_id: UUID,
    body: FeedUpdate,
    principal: Writer,
    db: Db,
    correlation_id: CorrelationId,
) -> FeedOut:
    channel, scanner, feed = save_feed(
        db,
        channel_id=channel_id,
        kind=body.kind,
        status=body.status,
        options=body.options,
        actor_user_id=principal.user.id,
        correlation_id=correlation_id,
    )
    return _out(db, channel, scanner, feed)
