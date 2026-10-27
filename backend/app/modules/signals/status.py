from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.modules.signals.clocks import CallClocks, stale_window, still_tracking
from app.modules.signals.models import Signal

IST = ZoneInfo("Asia/Kolkata")
_ENTRY_WINDOW = timedelta(minutes=30)
_GUIDES = {
    "waiting": (
        "Waiting",
        "The entry window is still open. No one-minute close above the trigger is recorded.",
    ),
    "window_over": (
        "Window over",
        "The entry window has ended. The one-minute bars are not in yet, "
        "so this is not Entry and not Not valid.",
    ),
    "stale": (
        "Stale",
        "This signal is stale. Quantivo will not treat it as executable.",
    ),
    "expired": (
        "Expired",
        "This signal has expired. It cannot be executed.",
    ),
    "no_symbol": (
        "No NSE",
        "This name did not match one NSE symbol. Quantivo will not treat it as executable.",
    ),
}

_WARNINGS = {
    "stale": "This signal is stale. Quantivo will not treat it as executable.",
    "expired": "This signal has expired. It cannot be executed.",
    "unmatched": (
        "This name did not match one NSE symbol. Quantivo will not treat it as executable."
    ),
    "ambiguous": (
        "This name matches more than one symbol. Quantivo will not treat it as executable."
    ),
}


def derived_status(signal: Signal, now: datetime, clocks: CallClocks | None = None) -> str:
    """Status comes from the match and the clocks. A stored status word is not read."""

    if signal.match_status != "matched":
        return signal.match_status
    if signal.expires_at <= now and not still_tracking(signal, now):
        return "expired"
    window = stale_window(signal, clocks or CallClocks())
    if window is not None and signal.published_at <= now - window:
        return "stale"
    return "active"


def warning_for(status: str) -> str | None:
    return _WARNINGS.get(status)


def is_executable(status: str) -> bool:
    return status == "active"


def guide_for(
    signal: Signal,
    now: datetime,
    clocks: CallClocks | None = None,
) -> tuple[str, str, str]:
    """One cue for the row, from the same activities as the call-progress flowchart."""

    status = derived_status(signal, now, clocks)
    if status in {"unmatched", "ambiguous"}:
        code = "no_symbol"
    elif status in {"expired", "stale"}:
        code = status
    elif _as_ist(now) < entry_deadline(signal.published_at):
        code = "waiting"
    else:
        code = "window_over"
    label, hint = _GUIDES[code]
    if status == "ambiguous":
        hint = (
            "This name matches more than one symbol. Quantivo will not treat it as executable."
        )
    return code, label, hint


def entry_deadline(published_at: datetime) -> datetime:
    """The window ends 30 minutes after the post, or at 15:30 IST, whichever is sooner."""

    sent = _as_ist(published_at)
    if sent.weekday() >= 5:
        return sent
    close = sent.replace(hour=15, minute=30, second=0, microsecond=0)
    if sent >= close:
        return sent
    return min(sent + _ENTRY_WINDOW, close)


def _as_ist(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=IST)
    return value.astimezone(IST)
